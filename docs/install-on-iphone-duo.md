# Installation of Duo Keyboard on an iPhone Duo from Windows

## Summary

Duo Keyboard installs on an iPhone Duo from Windows 11 with Sideloadly and a free Apple ID.
GitHub Actions builds the app on a hosted Mac, and Sideloadly signs the build on the PC.

1. Get the build: `gh run download -R YilongJu/iphone-duo-keyboard -n DuoKeyboard-unsigned-ipa -D build/latest`
2. Install Sideloadly, plus iTunes and iCloud from Apple's website.
3. Sign and install `build/latest/DuoKeyboard-unsigned.ipa` with Sideloadly over USB.
4. On the phone, trust the developer profile and turn on Developer Mode.
5. Add Duo Keyboard under Settings, General, Keyboard, Keyboards.
6. Unfold the phone, open any text field, and choose Duo Keyboard with the globe key.

This guide does not settle one question: public sources do not confirm that Sideloadly signs a
keyboard extension for iOS 27 on an iPhone Duo. The first install answers the question.

## Setup of Sideloadly on the Windows PC

1. Download Sideloadly from <https://sideloadly.io> and install it.
2. Install iTunes and iCloud with the installers from Apple's website. Sideloadly does not
   work with the Microsoft Store versions.
3. Connect the iPhone Duo with a USB cable, unlock it, and tap Trust.
4. Open iTunes once and confirm that iTunes shows the phone.

Sideloadly sends the Apple ID and password to Apple to request a signing certificate. A
second Apple ID made for this purpose keeps your main account's password out of the tool.

## Signing and installation with Sideloadly

1. Open Sideloadly. Select the iPhone Duo in the device list.
2. Drag `DuoKeyboard-unsigned.ipa` onto the IPA box.
3. Type the Apple ID in the Apple ID box.
4. Open Advanced Options and confirm that "Remove app extensions" is off. The keyboard is an
   app extension, so that option would delete the keyboard.
5. Click Start, then type the password and the two-factor code when Sideloadly asks.
6. Wait for the word "Done".

## Settings on the iPhone Duo

1. Open Settings, General, VPN & Device Management. Tap the Apple ID and tap Trust.
2. Open Settings, Privacy & Security, Developer Mode. Turn Developer Mode on and restart.
3. Open Settings, General, Keyboard, Keyboards, Add New Keyboard. Choose Duo Keyboard.
4. In any text field, hold the globe key and choose Duo Keyboard.

The app named Duo Keyboard also has a field that always shows the keyboard. That field works
before step 3, so the field tells you at once whether the layout looks right.

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

## Limits of a free Apple ID

| Limit | Value |
| --- | --- |
| Lifetime of one install | 7 days, then Sideloadly must sign the app again |
| Apps installed this way at one time | 3 |
| New app identifiers per week | 10, and this app uses 2 |

A paid Apple Developer Program account ($99 a year) removes the 7-day limit through TestFlight.

## Features outside this version

- Autocorrect and word suggestions
- Emoji and dictation keys
- Accent menus on a long press
- Up and down arrow keys, because iOS gives a keyboard extension only left and right movement
