# Guitar2Discord

Stream audio from any Windows application directly to a Discord voice channel.

![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2B-0078D6.svg)
![Tauri](https://img.shields.io/badge/Tauri-2.0-FFC131.svg)

## Overview

Guitar2Discord captures audio from a specific Windows application (like a DAW, guitar amp simulator, or any audio software) and streams it directly to a Discord voice channel via a bot. Perfect for remote jamming sessions, sharing music with friends, or streaming game audio.

## Features

- **Per-Application Audio Capture** - Select any running application to capture its audio output, without capturing system-wide audio
- **Discord Voice Streaming** - Stream captured audio to any voice channel your bot has access to
- **Secure Token Storage** - Bot token is stored securely in your system's credential manager
- **Modern UI** - Clean, dark-themed interface with real-time status indicators
- **Low Latency** - Uses WASAPI event-driven capture for minimal audio delay

## Requirements

- Windows 10 or later (uses WASAPI application loopback, a Windows 10+ feature)
- A Discord bot token with voice permissions
- [Rust](https://rustup.rs/) (for building from source)
- [Node.js](https://nodejs.org/) 18+ (for building from source)

## Discord Bot Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and add a bot
3. Under **Bot** settings:
   - Enable the **"Server Members Intent"** (if you want member info)
   - Copy the bot token
4. Under **OAuth2 > URL Generator**:
   - Select scopes: `bot`
   - Select bot permissions: `Connect`, `Speak`
   - Use the generated URL to invite the bot to your server

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/yourusername/guitar2discord.git
cd guitar2discord

# Install dependencies
npm install

# Run in development mode
npm run tauri dev

# Build for production
npm run tauri build
```

### Windows Quick Start

On Windows with Rust and CMake installed, you can use the included helper script:

```powershell
.\run-windows
```

## Usage

1. **Enter Bot Token** - Paste your Discord bot token and click "Save Token"
2. **Select Audio Source** - Choose the application you want to capture audio from
3. **Select Destination** - Pick the Discord server and voice channel
4. **Start Streaming** - Click "Start Streaming" to begin

The bot will join the selected voice channel and start playing the captured audio.

## Architecture

```
guitar2discord/
├── src/                    # Frontend (HTML/CSS/JS)
│   ├── index.html
│   ├── main.js
│   └── styles.css
└── src-tauri/              # Backend (Rust)
    └── src/
        ├── audio/          # WASAPI audio capture
        │   └── capture.rs
        ├── discord/        # Discord bot integration
        │   └── bot.rs
        ├── process/        # Process enumeration
        │   └── list.rs
        ├── commands.rs     # Tauri IPC commands
        └── lib.rs          # App entry point
```

### Key Technologies

| Component | Technology |
|-----------|------------|
| Desktop Framework | [Tauri 2](https://tauri.app/) |
| Audio Capture | [wasapi](https://crates.io/crates/wasapi) (WASAPI bindings) |
| Discord Bot | [serenity](https://crates.io/crates/serenity) |
| Voice Streaming | [songbird](https://crates.io/crates/songbird) |
| Async Runtime | [tokio](https://tokio.rs/) |
| Secure Storage | [keyring](https://crates.io/crates/keyring) |

## How It Works

1. **Audio Capture**: Uses Windows WASAPI application loopback to capture audio from a specific process. Audio is captured at 48kHz stereo (Discord's preferred format) with automatic format conversion.

2. **Audio Pipeline**: Captured samples are sent through an async channel to the Discord bot's audio source, which streams them to the voice channel.

3. **Discord Integration**: The app creates a Discord bot client using Serenity, joins the specified voice channel using Songbird, and plays the captured audio as a live stream.

## Troubleshooting

### No audio in Discord
- Make sure the source application is actually producing audio
- Check that the correct process is selected (some apps spawn multiple processes)
- Verify the bot has joined the voice channel (check Discord)

### Bot can't connect
- Verify your bot token is correct
- Check that the bot has been invited to the server with voice permissions
- Ensure the bot has permission to connect to and speak in the target channel

### Process not listed
- System processes are filtered out by default
- Some background processes may not appear
- Try refreshing the process list

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Tauri](https://tauri.app/) for the excellent desktop app framework
- [Serenity](https://github.com/serenity-rs/serenity) and [Songbird](https://github.com/serenity-rs/songbird) for Discord integration
- The Rust audio community for WASAPI bindings
