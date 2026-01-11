# Reddit to X Sharer Extension

Browser extension that adds "Share to X" buttons to Reddit posts and sends them to the Python automation script.

## Installation

### 1. Install Python dependencies
```bash
pip install flask flask-cors
```

### 2. Install Firefox Extension

1. Open Firefox
2. Go to `about:debugging#/runtime/this-firefox`
3. Click "Load Temporary Add-on"
4. Navigate to this folder and select `manifest.json`

### 3. Run the automation script
```bash
python XportReddit.py
```

## Usage

1. Start the Python script - it will start a local server and Edge browser
2. Browse Reddit in Firefox (or any browser with the extension)
3. Click "📤 Share to X" button on any post with images
4. The automation will automatically grab images and post to X!

## How it works

- Extension adds buttons to every Reddit post
- Clicking sends the post URL to `http://127.0.0.1:8765/share`
- Python Flask server receives it and queues for processing
- Selenium automation handles the rest!
