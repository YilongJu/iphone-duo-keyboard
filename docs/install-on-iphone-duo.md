# Installation of Duo Keyboard on an iPhone Duo through TestFlight

## Summary

Duo Keyboard reaches an iPhone Duo through TestFlight, with an Apple Developer Program
membership. A GitHub Actions workflow signs the build on a hosted Mac and uploads it. The
Apple ID password stays on Apple's own websites.

1. Enroll in the Apple Developer Program at <https://developer.apple.com/programs/enroll>.
2. Register the two app identifiers and create the app record in App Store Connect.
3. Create an App Store Connect API key and store four GitHub secrets.
4. Start the upload: `gh workflow run TestFlight -R YilongJu/iphone-duo-keyboard`
5. Install the build from the TestFlight app on the phone.
6. Add Duo Keyboard under Settings, General, Keyboard, Keyboards.

This guide does not settle one question: the TestFlight workflow has not run with real
credentials yet, so its signing step is untested.

## Terms in this guide

| Term | Meaning |
| --- | --- |
| App identifier | The unique name Apple uses for an app, such as `com.yilongju.duokeyboard` |
| App record | The entry for the app in App Store Connect, which TestFlight builds attach to |
| API key | A file that lets the build machine act for your team, in place of a password |
| GitHub secret | A value GitHub stores encrypted and shows only to the workflow |

## Enrollment in the Apple Developer Program

1. Open <https://developer.apple.com/programs/enroll> and sign in with your Apple ID.
2. Choose Individual. A personal bank account is enough if you later sell the app.
3. Pay the $99 yearly fee and wait for Apple's approval email.

Apple states 48 hours for approval. Forum reports in 2026 range from days to 9 weeks.

## App identifiers and app record

1. Open <https://developer.apple.com/account/resources/identifiers/list> and click the plus button.
2. Register an App ID with the identifier `com.yilongju.duokeyboard`.
3. Register a second App ID with the identifier `com.yilongju.duokeyboard.keyboard`.
4. Open <https://appstoreconnect.apple.com/apps>, click the plus button, and choose New App.
5. Choose iOS, the name "Duo Keyboard", and the identifier `com.yilongju.duokeyboard`.

App names are unique across the App Store. Choose another name if Apple rejects this one.

## API key and GitHub secrets

1. Open <https://appstoreconnect.apple.com/access/integrations/api>.
2. Create a team key with the Admin role. The Admin role lets the build create certificates.
3. Download the `.p8` file. Apple offers the download once.
4. Copy the Key ID and the Issuer ID from the same page.
5. Copy the Team ID from <https://developer.apple.com/account>, under Membership details.
6. Store the four values with these commands in a terminal:

```
gh secret set APPLE_TEAM_ID -R YilongJu/iphone-duo-keyboard
gh secret set ASC_KEY_ID -R YilongJu/iphone-duo-keyboard
gh secret set ASC_ISSUER_ID -R YilongJu/iphone-duo-keyboard
gh secret set ASC_KEY_P8 -R YilongJu/iphone-duo-keyboard < path\to\AuthKey_XXXXXXXXXX.p8
```

The first three commands ask you to paste the value. The repository is public, and GitHub
secrets stay hidden from visitors and from build logs.

## Upload and installation

1. Run `gh workflow run TestFlight -R YilongJu/iphone-duo-keyboard`.
2. Wait for the workflow to finish, then wait for Apple's processing email.
3. In App Store Connect, open the app's TestFlight tab and add yourself to an internal group.
4. Install the TestFlight app on the iPhone Duo and accept the invitation.
5. Install Duo Keyboard from TestFlight.
6. Open Settings, General, Keyboard, Keyboards, Add New Keyboard. Choose Duo Keyboard.
7. In any text field, hold the globe key and choose Duo Keyboard.

The app named Duo Keyboard also has a field that always shows the keyboard. That field works
before step 6, so the field tells you at once whether the layout looks right.

## Layouts by keyboard width

The keyboard measures its own width and picks a layout. The wide layout starts at 600 points.

| Phone position | Keyboard width | Layout |
| --- | --- | --- |
| Closed, portrait | about 466 pt | Compact: number row plus the phone letter rows |
| Closed, landscape | about 678 pt | Wide |
| Open, portrait | about 669 pt | Wide |
| Open, landscape | about 951 pt | Wide |

The more width the keyboard gets, the more keys each row holds: 10 in the compact layout and
14 in the wide layout. The wide layout adds a number row with shifted symbols, tab, caps
lock, brackets, a second shift key and two arrow keys.

## Measurements to send back after the first test

The space bar shows the keyboard's own measurements, for example `669x250 hR vR safe 0/0/0 globe 0`.
The widths in the table above come from the simulator, so the real values matter. Send a
screenshot of the keyboard in each of the four phone positions.

## Features outside this version

- Autocorrect and word suggestions
- Emoji and dictation keys
- Accent menus on a long press
- Up and down arrow keys, because iOS gives a keyboard extension only left and right movement
