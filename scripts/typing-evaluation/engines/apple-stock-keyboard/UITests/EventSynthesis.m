#import "EventSynthesis.h"

#import <UIKit/UIKit.h>
#import <XCTest/XCTest.h>
#import <unistd.h>

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

/// Builds the event record of one tap. Returns nil with an error when XCTest does not hold the
/// event classes.
static id<EvalEventRecord> EvalTapRecord(CGPoint point, double hold, NSError **error) {
    Class pathClass = NSClassFromString(@"XCPointerEventPath");
    Class recordClass = NSClassFromString(@"XCSynthesizedEventRecord");
    if (pathClass == Nil || recordClass == Nil) {
        if (error) { *error = EvalError(@"XCTest does not hold the classes XCPointerEventPath and XCSynthesizedEventRecord"); }
        return nil;
    }
    if (![pathClass instancesRespondToSelector:@selector(initForTouchAtPoint:offset:)]
        || ![pathClass instancesRespondToSelector:@selector(liftUpAtOffset:)]
        || ![recordClass instancesRespondToSelector:@selector(initWithName:interfaceOrientation:)]
        || ![recordClass instancesRespondToSelector:@selector(addPointerEventPath:)]) {
        if (error) { *error = EvalError(@"the XCTest event classes do not answer the selectors this file calls"); }
        return nil;
    }
    // Orientation 1 is portrait. The host app supports portrait only.
    id<EvalEventRecord> record = [(id<EvalEventRecord>)[recordClass alloc] initWithName:@"typing evaluation tap"
                                                                    interfaceOrientation:1];
    id<EvalPointerEventPath> path = [(id<EvalPointerEventPath>)[pathClass alloc] initForTouchAtPoint:point offset:0.0];
    [path liftUpAtOffset:hold];
    [record addPointerEventPath:path];
    return record;
}

static id<EvalEventSynthesizer> EvalSynthesizer(NSError **error) {
    id device = XCUIDevice.sharedDevice;
    if ([device respondsToSelector:@selector(eventSynthesizer)]) {
        id<EvalEventSynthesizer> synthesizer = [(id<EvalDevice>)device eventSynthesizer];
        if (synthesizer != nil && [synthesizer respondsToSelector:@selector(synthesizeEvent:completion:)]) {
            return synthesizer;
        }
    }
    if (error) { *error = EvalError(@"XCUIDevice does not offer an event synthesizer with synthesizeEvent:completion:"); }
    return nil;
}

@implementation EventSynthesis

+ (NSArray<NSNumber *> *)tapPointsPaced:(NSArray<NSValue *> *)points
                               interval:(double)interval
                                   hold:(double)hold
                                  error:(NSError **)error {
    if (points.count == 0) {
        if (error) { *error = EvalError(@"points must hold at least one value"); }
        return nil;
    }
    id<EvalEventSynthesizer> synthesizer = EvalSynthesizer(error);
    if (synthesizer == nil) {
        return nil;
    }
    NSMutableArray<NSNumber *> *times = [NSMutableArray arrayWithCapacity:points.count];
    NSDate *begin = nil;
    NSDate *lastSend = nil;
    for (NSValue *value in points) {
        // Each tap is due one interval after the tap before it was sent.
        if (lastSend != nil) {
            NSDate *due = [lastSend dateByAddingTimeInterval:interval];
            if (due.timeIntervalSinceNow > 0) {
                [NSThread sleepUntilDate:due];
            }
        }
        id<EvalEventRecord> record = EvalTapRecord(value.CGPointValue, hold, error);
        if (record == nil) {
            return nil;
        }
        __block BOOL finished = NO;
        __block NSError *synthesisError = nil;
        lastSend = [NSDate date];
        if (begin == nil) {
            begin = lastSend;
        }
        [times addObject:@([lastSend timeIntervalSinceDate:begin])];
        [synthesizer synthesizeEvent:record completion:^(BOOL result, NSError *invokeError) {
            synthesisError = invokeError;
            finished = YES;
        }];
        // The test daemon performs one gesture at a time, so the next tap waits for this one.
        // The completion block can arrive on the main queue, so this thread runs its run loop
        // while it waits.
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:30.0];
        while (!finished && deadline.timeIntervalSinceNow > 0) {
            [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
            usleep(1000);
        }
        if (!finished) {
            if (error) { *error = EvalError(@"the event synthesizer did not finish a tap in 30 seconds"); }
            return nil;
        }
        if (synthesisError != nil) {
            if (error) { *error = synthesisError; }
            return nil;
        }
    }
    return times;
}

@end
