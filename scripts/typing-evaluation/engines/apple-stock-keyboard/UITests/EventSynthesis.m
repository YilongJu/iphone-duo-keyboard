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

/// Builds one event record with a tap at each point. Returns nil with an error when XCTest does
/// not hold the event classes.
static id<EvalEventRecord> EvalRecord(NSArray<NSValue *> *points, NSArray<NSNumber *> *starts, double hold, NSError **error) {
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
    id<EvalEventRecord> record = [(id<EvalEventRecord>)[recordClass alloc] initWithName:@"typing evaluation taps"
                                                                    interfaceOrientation:1];
    for (NSUInteger index = 0; index < points.count; index++) {
        double start = starts[index].doubleValue;
        id<EvalPointerEventPath> path = [(id<EvalPointerEventPath>)[pathClass alloc] initForTouchAtPoint:points[index].CGPointValue
                                                                                                    offset:start];
        [path liftUpAtOffset:start + hold];
        [record addPointerEventPath:path];
    }
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

/// Runs the run loop of this thread until the block returns YES or the time runs out. A
/// completion block of the synthesizer can arrive on the main queue, so the thread must not block.
static void EvalRunLoopUntil(BOOL (^done)(void), NSTimeInterval timeout) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:timeout];
    while (!done() && deadline.timeIntervalSinceNow > 0) {
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
        usleep(1000);
    }
}

@implementation EventSynthesis

+ (NSArray<NSNumber *> *)tapPointsPaced:(NSArray<NSValue *> *)points
                               interval:(double)interval
                                   hold:(double)hold
                      waitForCompletion:(BOOL)waitForCompletion
                                  error:(NSError **)error {
    if (points.count == 0) {
        if (error) { *error = EvalError(@"points must hold at least one value"); }
        return nil;
    }
    id<EvalEventSynthesizer> synthesizer = EvalSynthesizer(error);
    if (synthesizer == nil) {
        return nil;
    }
    __block NSInteger finished = 0;
    __block NSError *firstError = nil;
    NSMutableArray<NSNumber *> *times = [NSMutableArray arrayWithCapacity:points.count];
    NSDate *begin = [NSDate date];
    for (NSUInteger index = 0; index < points.count; index++) {
        NSDate *due = [begin dateByAddingTimeInterval:index * interval];
        if (due.timeIntervalSinceNow > 0) {
            [NSThread sleepUntilDate:due];
        }
        id<EvalEventRecord> record = EvalRecord(@[points[index]], @[@0.0], hold, error);
        if (record == nil) {
            return nil;
        }
        [times addObject:@(-begin.timeIntervalSinceNow)];
        [synthesizer synthesizeEvent:record completion:^(BOOL result, NSError *invokeError) {
            if (invokeError != nil && firstError == nil) {
                firstError = invokeError;
            }
            finished += 1;
        }];
        if (waitForCompletion) {
            NSInteger needed = (NSInteger)index + 1;
            EvalRunLoopUntil(^BOOL { return finished >= needed; }, 30.0);
            if (finished < needed) {
                if (error) { *error = EvalError(@"the event synthesizer did not finish a tap in 30 seconds"); }
                return nil;
            }
        }
    }
    NSInteger total = (NSInteger)points.count;
    EvalRunLoopUntil(^BOOL { return finished >= total; }, 30.0);
    if (finished < total) {
        if (error) { *error = EvalError(@"the event synthesizer did not finish every tap in 30 seconds"); }
        return nil;
    }
    if (firstError != nil) {
        if (error) { *error = firstError; }
        return nil;
    }
    return times;
}

+ (BOOL)tapPoints:(NSArray<NSValue *> *)points
           starts:(NSArray<NSNumber *> *)starts
             hold:(double)hold
            error:(NSError **)error {
    if (points.count == 0 || points.count != starts.count) {
        if (error) { *error = EvalError(@"points and starts must hold the same number of values, at least one"); }
        return NO;
    }
    id<EvalEventSynthesizer> synthesizer = EvalSynthesizer(error);
    if (synthesizer == nil) {
        return NO;
    }
    id<EvalEventRecord> record = EvalRecord(points, starts, hold, error);
    if (record == nil) {
        return NO;
    }
    __block BOOL finished = NO;
    __block NSError *synthesisError = nil;
    [synthesizer synthesizeEvent:record completion:^(BOOL result, NSError *invokeError) {
        synthesisError = invokeError;
        finished = YES;
    }];
    EvalRunLoopUntil(^BOOL { return finished; }, starts.lastObject.doubleValue + hold + 30.0);
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

@end
