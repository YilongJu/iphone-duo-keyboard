#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Sends taps to the simulator through the event synthesizer of XCTest.
///
/// XCUICoordinate.tap() waits for the app to become idle before each tap, so the test cannot set
/// the time between two taps. This class sends each tap as its own synthesized event at a time
/// the caller sets. The class reaches the event classes of XCTest by name at run time, because
/// XCTest does not publish them in a header.
@interface EventSynthesis : NSObject

/// Taps each point in order, one synthesized event for each tap. `points` holds CGPoint values
/// in screen coordinates. The tap with index k starts `k * interval` seconds after the first
/// tap. Each finger lifts `hold` seconds after its touch-down.
///
/// With `waitForCompletion` set, a tap also waits for the event of the tap before it, so the
/// time between two taps can exceed `interval` when the test daemon is slow. Without it, the
/// method sends each event at its time and collects the completions at the end.
///
/// Returns the time each event was sent, in seconds since the first event, or nil with an error.
+ (nullable NSArray<NSNumber *> *)tapPointsPaced:(NSArray<NSValue *> *)points
                                        interval:(double)interval
                                            hold:(double)hold
                               waitForCompletion:(BOOL)waitForCompletion
                                           error:(NSError **)error;

/// Taps each point in order as one synthesized event that holds every tap. `starts` holds the
/// time of each touch-down in seconds from the start of the event, as NSNumber values.
/// The trial of this method showed that the simulator plays such an event faster than the
/// times in `starts`, so the measurement does not use it.
+ (BOOL)tapPoints:(NSArray<NSValue *> *)points
           starts:(NSArray<NSNumber *> *)starts
             hold:(double)hold
            error:(NSError **)error;

@end

NS_ASSUME_NONNULL_END
