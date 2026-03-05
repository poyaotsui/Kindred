# Sign Up / Sign In Setup

## How to run (fix "Cannot GET /signup" or "Cannot GET /signin")

Sign In and Sign Up only work when the app is served by the **Flask server**. If you open the HTML file directly or use another server (e.g. Live Server), you'll get "Cannot GET /signup" or "Cannot GET /signin".

1. **Stop** any other server (e.g. VS Code Live Server) that might be using port 5000 or serving your project.
2. From the project root run:
   ```bash
   cd ~/Desktop/vscode_py
   python webapp/app.py
   ```
3. In your browser, open **only** this address: **http://127.0.0.1:5000**
4. From that page, click Sign In or Sign Up. The links will work because the same server handles `/signin` and `/signup`.

---

## Phone verification (SMS)

By default, the app runs in **demo mode**: verification codes are printed to the terminal instead of sent via SMS. This lets you test sign-up without a Twilio account.

### Enable real SMS with Twilio

1. Create a [Twilio](https://www.twilio.com) account (free trial available).
2. Get your **Account SID**, **Auth Token**, and a **Phone Number** from the Twilio console.
3. Set these environment variables before running the app:

```bash
export TWILIO_ACCOUNT_SID="your_account_sid"
export TWILIO_AUTH_TOKEN="your_auth_token"
export TWILIO_PHONE_NUMBER="+15551234567"
python app.py
```

4. Install Twilio: `pip install twilio`

### Sign-up flow

- **Gmail only**: Users must use an `@gmail.com` address.
- **Phone**: Entered during sign-up; receives a 6-digit verification code.
- **Password**: At least 6 characters.

### Sign-in flow

- Gmail address + password.

### GIF search (Tenor) on the board

To enable “Search GIFs” in the Add-to-board modal, get a free API key from [Tenor Developer](https://tenor.com/developer/dashboard) and set:

```bash
export TENOR_API_KEY="your_tenor_api_key"
```
