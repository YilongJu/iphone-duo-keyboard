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
/// in screen coordinates. The method sends each tap `interval` seconds after it sent the tap
/// before it, and waits for the event of each tap to finish. Each finger lifts `hold` seconds
/// after its touch-down. The time between two taps exceeds `interval` when the test daemon
/// takes longer than `interval` for one event.
///
/// Returns the time each event was sent, in seconds since the first event, or nil with an error.
+ (nullable NSArray<NSNumber *> *)tapPointsPaced:(NSArray<NSValue *> *)points
                                        interval:(double)interval
                                            hold:(double)hold
                                           error:(NSError **)error;

@end

NS_ASSUME_NONNULL_END
