// Background service worker for handling requests to localhost
// This is required in Manifest V3 because content scripts can't directly fetch to localhost

// Keep service worker alive
let keepAliveInterval;
function keepAlive() {
    keepAliveInterval = setInterval(() => {
        console.log('Service worker keepalive');
    }, 20000); // Every 20 seconds
}
keepAlive();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'SHARE_TO_X') {
        const { url } = message;
        
        console.log('Background: Sending request to server for URL:', url);
        
        fetch('http://127.0.0.1:8765/share', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Background: Server response:', data);
            sendResponse({ success: true, data: data });
        })
        .catch(error => {
            console.error('Background fetch error:', error);
            sendResponse({ success: false, error: error.message });
        });
        
        // Return true to indicate we'll send response asynchronously
        return true;
    } else if (message.type === 'CHECK_STATUS') {
        const { url } = message;
        
        // URL encode the reddit URL for the path parameter
        const encodedUrl = encodeURIComponent(url);
        
        fetch(`http://127.0.0.1:8765/check/${encodedUrl}`, {
            method: 'GET',
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            sendResponse({ success: true, data: data });
        })
        .catch(error => {
            console.error('Background status check error:', error);
            sendResponse({ success: false, error: error.message });
        });
        
        // Return true to indicate we'll send response asynchronously
        return true;
    }
});

// Log when service worker starts
console.log('Reddit to X background service worker started');
