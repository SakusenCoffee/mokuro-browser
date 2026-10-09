# Privacy Policy for Mokuro Browser

Last updated: October 9, 2026

Mokuro Browser is a local manga OCR companion. This policy describes how its browser extension and desktop application handle data.

## Data handled

When you explicitly request a scan, the extension reads the selected image or visible manga image from the current webpage. It sends that image to the Mokuro Browser OCR server running on your own computer at `http://127.0.0.1:8766`. The resulting recognized text and text-position data are returned to the extension so it can display selectable text over the image.

The extension may store its settings, local pairing information, and temporary OCR results on your device. If you enable reading history, the desktop application stores your saved reading history locally on your device.

## No external collection or sharing

Mokuro Browser does not send webpage images, recognized text, browsing activity, pairing information, or reading history to the developer, to analytics services, or to third parties. It does not sell user data, use it for advertising, or use it to determine creditworthiness or for lending purposes.

The extension requests access to webpages only to provide the user-requested OCR and text-overlay features. Native messaging is used only to control the user-installed local Mokuro Browser server.

## Data control and retention

Local extension data can be removed by uninstalling the extension or clearing its browser storage. Reading history can be disabled or deleted in the Mokuro Browser dashboard. Uninstalling the desktop application or deleting its application data removes its locally stored data.

## Security

Communication between the extension and its companion OCR server is limited to the loopback address on the user's own device. The local server requires a pairing token before it accepts extension requests.

## Chrome Web Store Limited Use

Mokuro Browser's use of information received from Chrome APIs adheres to the [Chrome Web Store User Data Policy](https://developer.chrome.com/docs/webstore/program-policies/user-data), including the Limited Use requirements.

## Contact

For privacy questions, contact the publisher through the support contact listed on the Mokuro Browser Chrome Web Store page or through the project's GitHub issue tracker.
