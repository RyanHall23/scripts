// Track posts being processed to prevent duplicates
const processingPosts = new Set();

// Poll for completion status
function pollForCompletion(postUrl, button) {
    const maxAttempts = 120; // Poll for up to 2 minutes (120 * 1 second)
    let attempts = 0;
    
    const checkStatus = () => {
        if (attempts >= maxAttempts) {
            console.log('Polling timed out for:', postUrl);
            return;
        }
        
        attempts++;
        
        // Use chrome.runtime.sendMessage to check status via background script
        chrome.runtime.sendMessage({
            type: 'CHECK_STATUS',
            url: postUrl
        }, (response) => {
            if (!response || !response.success) {
                // Server might be down, stop polling
                console.error('Failed to check status:', response?.error);
                return;
            }
            
            const status = response.data?.status;
            
            if (status === 'completed') {
                button.innerHTML = '✅ Shared!';
                button.style.background = '#10b981';
                processingPosts.delete(postUrl);
            } else if (status === 'failed') {
                button.innerHTML = '❌ Failed';
                button.style.background = '#ef4444';
                processingPosts.delete(postUrl);
                button.disabled = false;
                setTimeout(() => {
                    button.innerHTML = '📤 Share to X';
                    button.style.background = '';
                }, 5000);
            } else if (status === 'processing') {
                // Still processing, check again
                setTimeout(checkStatus, 1000);
            } else {
                // Unknown status, stop polling
                console.log('Unknown status:', status);
            }
        });
    };
    
    // Start polling after 2 seconds
    setTimeout(checkStatus, 2000);
}

// Add "Share to X" button to Reddit posts
function addShareButton(postElement) {
    // Check if button already exists
    if (postElement.querySelector('.share-to-x-btn')) return;
    
    // Get the post URL - try multiple selectors for different Reddit layouts
    let postUrl = null;
    
    // New Reddit - try to get from the post itself
    const postLink = postElement.querySelector('a[slot="full-post-link"]') ||
                     postElement.querySelector('a[data-click-id="body"]') ||
                     postElement.querySelector('a[href*="/comments/"]') ||
                     postElement.querySelector('[data-testid="post-title"]');
    
    if (postLink) {
        postUrl = postLink.href || postLink.getAttribute('href');
    }
    
    // Old Reddit
    if (!postUrl) {
        const titleLink = postElement.querySelector('.title a.title');
        if (titleLink) postUrl = titleLink.href;
    }
    
    // Fallback: construct from data-permalink
    if (!postUrl) {
        const permalink = postElement.getAttribute('data-permalink');
        if (permalink) postUrl = 'https://www.reddit.com' + permalink;
    }
    
    if (!postUrl || !postUrl.includes('/comments/')) return;
    
    postUrl = postUrl.split('?')[0]; // Clean URL
    
    // Create share button
    const button = document.createElement('button');
    button.className = 'share-to-x-btn';
    button.innerHTML = '📤 Share to X';
    button.title = 'Share this post to X/Twitter via automation';
    button.style.zIndex = '9999';
    button.style.pointerEvents = 'auto';
    
    button.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        
        // Prevent duplicate submissions
        if (processingPosts.has(postUrl)) {
            console.log('Post already being processed:', postUrl);
            return;
        }
        
        button.innerHTML = '⏳ Sending...';
        button.disabled = true;
        processingPosts.add(postUrl);
        
        try {
            // Use chrome.runtime.sendMessage to communicate with background script
            // This is required in Manifest V3 for localhost requests
            const response = await chrome.runtime.sendMessage({
                type: 'SHARE_TO_X',
                url: postUrl
            });
            
            if (response && response.success && response.data.status === 'success') {
                button.innerHTML = '📥 Processing...';
                button.style.background = '#3b82f6';
                button.style.cursor = 'not-allowed';
                
                // Poll for completion status
                pollForCompletion(postUrl, button);
            } else {
                throw new Error(response?.data?.message || response?.error || 'Unknown error');
            }
        } catch (error) {
            // Only remove from processing set on error
            processingPosts.delete(postUrl);
            
            button.innerHTML = '❌ Failed';
            button.style.background = '#ef4444';
            console.error('Share to X error:', error);
            
            // Check for connection errors
            if (error.message && error.message.includes('Extension context invalidated')) {
                alert('⚠️ Extension reloaded!\n\nPlease refresh this Reddit page.');
            } else if (error.message && error.message.includes('message port closed')) {
                alert('⚠️ Extension connection lost!\n\nPlease refresh this Reddit page.');
            } else if (error.message && (error.message.includes('Failed to fetch') || error.message.includes('NetworkError') || error.message.includes('fetch'))){
                alert('⚠️ Automation server not running!\n\nPlease start: python XportReddit.py');
            } else if (!chrome.runtime?.id) {
                alert('⚠️ Extension disconnected!\n\nPlease refresh this Reddit page.');
            } else {
                console.error('Server error:', error.message);
                alert(`⚠️ Error: ${error.message}`);
            }
            
            setTimeout(() => {
                button.innerHTML = '📤 Share to X';
                button.style.background = '';
                button.disabled = false;
            }, 3000);
        }
    });
    
    // Find a good place to insert the button - try multiple locations
    let inserted = false;
    
    // New Reddit - action buttons area
    const actionButtons = postElement.querySelector('[data-testid="post-action-buttons-container"]') ||
                         postElement.querySelector('div[slot="actionButtons"]');
    
    if (actionButtons) {
        const wrapper = document.createElement('div');
        wrapper.style.display = 'inline-flex';
        wrapper.style.alignItems = 'center';
        wrapper.style.marginLeft = '8px';
        wrapper.style.position = 'relative';
        wrapper.style.zIndex = '9999';
        wrapper.style.pointerEvents = 'auto';
        wrapper.appendChild(button);
        actionButtons.appendChild(wrapper);
        inserted = true;
    }
    
    // Old Reddit - flat-list buttons
    if (!inserted) {
        const flatList = postElement.querySelector('.flat-list.buttons');
        if (flatList) {
            const li = document.createElement('li');
            li.appendChild(button);
            flatList.appendChild(li);
            inserted = true;
        }
    }
    
    // Fallback - append to post element
    if (!inserted) {
        const wrapper = document.createElement('div');
        wrapper.style.padding = '8px';
        wrapper.appendChild(button);
        postElement.appendChild(wrapper);
    }
}

// Add buttons to all posts on page
function addButtonsToAllPosts() {
    console.log('🔍 Scanning for Reddit posts...');
    
    // New Reddit selectors
    const newRedditPosts = document.querySelectorAll('shreddit-post, [data-testid="post-container"]');
    console.log(`Found ${newRedditPosts.length} new Reddit posts`);
    newRedditPosts.forEach(addShareButton);
    
    // Old Reddit selectors
    const oldRedditPosts = document.querySelectorAll('.thing.link');
    console.log(`Found ${oldRedditPosts.length} old Reddit posts`);
    oldRedditPosts.forEach(addShareButton);
}

// Initial load with delay
console.log('✅ Reddit to X Sharer extension loaded!');
setTimeout(() => {
    addButtonsToAllPosts();
}, 2000);

// Watch for new posts (infinite scroll)
const observer = new MutationObserver(() => {
    addButtonsToAllPosts();
});

observer.observe(document.body, {
    childList: true,
    subtree: true
});
