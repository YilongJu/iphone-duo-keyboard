#import "EventSynthesis.h"

#import <UIKit/UIKit.h>
#import <XCTest/XCTest.h>

// The selectors of the XCTest event classes this file calls. The classes are XCPointerEventPath
// and XCSynthesizedEventRecord, and the object that XCUIDevice returns from eventSynthesizer.
// The file finds the classes with NSClassFromString and checks each selector before the call.
@protocol EvalPointerEventPath <NSObject>
- (instancetype)initForTouchAtPoint:(CGPoint)point offset:(double)offset;
- (void)liftUpAtOffset:(double)offset;
@end

@protocol EvalEventRecord <NSObject>
- (instancetype)initWithName:(NSString *)name interfaceOrientation:(long long)orientation;
- (void)addPointerEventPath:(id)path;
- (BOOL)synthesizeWithError:(NSError **)error;
@end

@protocol EvalEventSynthesizer <NSObject>
- (void)synthesizeEvent:(id)event completion:(void (^)(BOOL, NSError *))completion;
@end

@protocol EvalDevice <NSObject>
- (id<EvalEventSynthesizer>)eventSynthesizer;
@end

static NSError *EvalError(NSString *message) {
    return [NSError errorWithDomain:@"EventSynthesis" code:1 userInfo:@{NSLocalizedDescriptionKey: message}];
}

@implementation EventSynthesis

+ (BOOL)tapPoints:(NSArray<NSValue *> *)points
           starts:(NSArray<NSNumber *> *)starts
             hold:(double)hold
            error:(NSError **)error {
    if (points.count == 0 || points.count != starts.count) {
        if (error) { *error = EvalError(@"points and starts must hold the same number of values, at least one"); }
        return NO;
    }
    Class pathClass = NSClassFromString(@"XCPointerEventPath");
    Class recordClass = NSClassFromString(@"XCSynthesizedEventRecord");
    if (pathClass == Nil || recordClass == Nil) {
        if (error) { *error = EvalError(@"XCTest does not hold the classes XCPointerEventPath and XCSynthesizedEventRecord"); }
        return NO;
    }
    if (![pathClass instancesRespondToSelector:@selector(initForTouchAtPoint:offset:)]
        || ![pathClass instancesRespondToSelector:@selector(liftUpAtOffset:)]
        || ![recordClass instancesRespondToSelector:@selector(initWithName:interfaceOrientation:)]
        || ![recordClass instancesRespondToSelector:@selector(addPointerEventPath:)]) {
        if (error) { *error = EvalError(@"the XCTest event classes do not answer the selectors this file calls"); }
        return NO;
    }

    // Orientation 1 is portrait. The host app supports portrait only.
    id<EvalEventRecord> record = [(id<EvalEventRecord>)[recordClass alloc] initWithName:@"typing evaluation taps"
                                                                    interfaceOrientation:1];
    double end = 0.0;
    for (NSUInteger index = 0; index < points.count; index++) {
        CGPoint point = points[index].CGPointValue;
        double start = starts[index].doubleValue;
        id<EvalPointerEventPath> path = [(id<EvalPointerEventPath>)[pathClass alloc] initForTouchAtPoint:point offset:start];
        [path liftUpAtOffset:start + hold];
        [record addPointerEventPath:path];
        end = MAX(end, start + hold);
    }

    id device = XCUIDevice.sharedDevice;
    if ([device respondsToSelector:@selector(eventSynthesizer)]) {
        id<EvalEventSynthesizer> synthesizer = [(id<EvalDevice>)device eventSynthesizer];
        if (synthesizer != nil && [synthesizer respondsToSelector:@selector(synthesizeEvent:completion:)]) {
            __block BOOL finished = NO;
            __block NSError *synthesisError = nil;
            [synthesizer synthesizeEvent:record completion:^(BOOL result, NSError *invokeError) {
                synthesisError = invokeError;
                finished = YES;
            }];
            // The completion block can arrive on the main queue, so this thread runs the run loop
            // while it waits.
            NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:end + 30.0];
            while (!finished && deadline.timeIntervalSinceNow > 0) {
                [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
            }
            if (!finished) {
                if (error) { *error = EvalError(@"the event synthesizer did not finish in time"); }
                return NO;
            }
            if (synthesisError != nil) {
                if (error) { *error = synthesisError; }
                return NO;
            }
            return YES;
        }
    }
    if ([(id)record respondsToSelector:@selector(synthesizeWithError:)]) {
        return [record synthesizeWithError:error];
    }
    if (error) { *error = EvalError(@"XCTest does not offer eventSynthesizer or synthesizeWithError:"); }
    return NO;
}

@end
