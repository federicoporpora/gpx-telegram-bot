# GPX HR Merger Bot

![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A Telegram bot interface for the **GPX HR Merger** tool. This bot allows you to easily merge Heart Rate data into a GPS track and recalibrate your activity distance directly from your phone.

## 📝 Overview

The **GPX HR Merger Bot** provides a convenient way to process your `.gpx` files without needing to use the command line. It's particularly useful for athletes who want to fix their activity data on the go before uploading it to platforms like Strava or Garmin Connect.

The bot automatically identifies which file contains the GPS track and which contains the Heart Rate data based on their content, merges them, and applies a distance correction if requested.

## ✨ Features

*   **Easy Interaction:** Send two files and a number (distance in km) to get your merged activity.
*   **Automatic Identification:** No need to rename files; the bot automatically distinguishes between GPS and HR data.
*   **Strava Integration:** A custom implementation for the author automatically uploads the activity to Strava.
*   **Mobile Friendly:** Designed to be used effortlessly from the Telegram mobile app.
*   **Zero Local Setup:** If you use the hosted version, no installation is required on your part.

### 🚀 Strava Auto-Upload
The current implementation includes an automatic upload feature to Strava specifically configured for my personal account. The bot detects my Telegram ID and handles the API authentication to push the processed file directly to my Strava profile.

**If you would like to have this automatic upload feature for your own account, please feel free to reach out to me on GitHub or via email at [porporafederico@gmail.com](mailto:porporafederico@gmail.com).**

## 💻 Requirements

To run your own instance of the bot, you will need:
*   🐍 **Python 3.9** or higher.
*   📦 **Dependencies:** `python-telegram-bot`, `requests`.
*   🤖 **Telegram Bot Token:** Obtained from [@BotFather](https://t.me/BotFather).
*   🌐 **Hosting:** (Optional) A service like Render or Heroku to keep the bot online 24/7.

## 📥 Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/YOUR_USERNAME/gpx-telegram-bot.git
    cd gpx-telegram-bot
    ```

2.  Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```

3.  Set up your environment variables:
    *   `TELEGRAM_TOKEN`: Your bot token from BotFather.
    *   `STRAVA_CLIENT_SECRET`: (Optional) Your Strava API client secret.
    *   `STRAVA_REFRESH_TOKEN`: (Optional) Your Strava API refresh token.
    *   `PORT`: (Optional) Port for the dummy health-check server (defaults to 10000).

## 🚀 Usage

1.  Start the bot:
    ```bash
    python bot.py
    ```

2.  In Telegram, search for your bot and send the `/start` command.
3.  Upload your two `.gpx` files (GPS track and Heart Rate source).
4.  Send a message with the **target distance in kilometers** (e.g., `10.5`).
5.  The bot will process the files and send you back a `.tcx` file ready for upload.

## 📂 Project Structure

```text
.
├── bot.py              # Telegram bot handler and Strava integration
├── gpx_hr_merger.py    # Core processing logic
├── requirements.txt    # Python dependencies
├── LICENSE             # MIT License
└── README.md           # Documentation
```

## ⚙️ Technical Details

The bot uses the `python-telegram-bot` library with asynchronous handlers. It utilizes a simple `HTTPServer` running in a separate thread to satisfy the health-check requirements of hosting platforms like Render. The core logic for merging and calibrating the GPX files is imported from `gpx_hr_merger.py`.

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
