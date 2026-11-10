#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Sends several taps to the simulator as one synthesized event.
///
/// XCUICoordinate.tap() makes one round trip to the test daemon for each tap. This class puts
/// every tap of a word into one event record, so the word costs one round trip and the taps keep
/// a fixed rhythm. The class reaches the event classes of XCTest by name at run time, because
/// XCTest does not publish them in a header.
@interface EventSynthesis : NSObject

/// Taps each point in order. `points` holds CGPoint values in screen coordinates. `starts` holds
/// the time of each touch-down in seconds from the start of the event, as NSNumber values. Each
/// finger lifts `hold` seconds after its touch-down.
+ (BOOL)tapPoints:(NSArray<NSValue *> *)points
           starts:(NSArray<NSNumber *> *)starts
             hold:(double)hold
            error:(NSError **)error;

@end

NS_ASSUME_NONNULL_END
