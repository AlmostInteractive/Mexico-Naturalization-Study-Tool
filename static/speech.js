/**
 * Shared Text-to-Speech functionality for consistent voice across the site
 */

// Global speech settings
let speechEnabled = localStorage.getItem('speechEnabled') !== 'false'; // Default to enabled
let speechRate = parseFloat(localStorage.getItem('speechRate')) || 1.0; // Default to normal speed
let currentUtterance = null;
let selectedVoice = null;
let voicesLoaded = false;
let speechQueue = [];
let hasSpanishVoice = false;
let hasSeenModal = false;
let isInitialized = false;

/**
 * Find and select the best Spanish voice, storing the choice in localStorage
 */
function selectSpanishVoice() {
    const voices = speechSynthesis.getVoices();

    if (voices.length === 0) {
        return null;
    }

    // Try to use previously selected voice by name
    const savedVoiceName = localStorage.getItem('selectedVoiceName');
    if (savedVoiceName) {
        const savedVoice = voices.find(voice => voice.name === savedVoiceName);
        if (savedVoice) {
            selectedVoice = savedVoice;
            voicesLoaded = true;
            hasSpanishVoice = true;
            console.log('Using saved voice:', selectedVoice.name, '(' + selectedVoice.lang + ')');
            return selectedVoice;
        }
    }

    // Priority order: es-MX > es-US > any Spanish voice
    let spanishVoice = voices.find(voice => voice.lang === 'es-MX');
    if (!spanishVoice) {
        spanishVoice = voices.find(voice => voice.lang === 'es-US');
    }
    if (!spanishVoice) {
        spanishVoice = voices.find(voice =>
            voice.lang.startsWith('es') ||
            voice.name.toLowerCase().includes('spanish') ||
            voice.name.toLowerCase().includes('español')
        );
    }

    if (spanishVoice) {
        selectedVoice = spanishVoice;
        voicesLoaded = true;
        hasSpanishVoice = true;
        // Save the voice name for consistency across pages
        localStorage.setItem('selectedVoiceName', spanishVoice.name);
        console.log('Selected Spanish voice:', spanishVoice.name, '(' + spanishVoice.lang + ')');
    } else {
        console.warn('No Spanish voice found - silently disabling speech');
        voicesLoaded = true;
        hasSpanishVoice = false;
        // Silently disable speech
        speechEnabled = false;
        localStorage.setItem('speechEnabled', 'false');

        // Show modal if we haven't offered help before or if no Spanish voice if we've already shown the modal
        hasSeenModal |= (localStorage.getItem('hasSeenVoiceModal') === 'true');
        if (!hasSeenModal) {
            showNoVoiceModal();
        }
    }

    return selectedVoice;
}

/**
 * Load voices and select the best Spanish voice
 */
function loadVoices() {
    selectSpanishVoice();

    const voices = speechSynthesis.getVoices();
    const spanishVoices = voices.filter(voice =>
        voice.lang.startsWith('es') ||
        voice.name.toLowerCase().includes('spanish') ||
        voice.name.toLowerCase().includes('español')
    );
    if (spanishVoices.length > 0) {
        console.log('Available Spanish voices:', spanishVoices.map(v => `${v.name} (${v.lang})`));
    }

    // Update UI to reflect voice availability
    updateSpeechToggleButton();

    // Process any queued speech requests
    if (voicesLoaded && speechQueue.length > 0 && hasSpanishVoice) {
        console.log('Processing', speechQueue.length, 'queued speech requests');
        while (speechQueue.length > 0) {
            const {text, onComplete} = speechQueue.shift();
            speakTextNow(text, onComplete);
        }
    } else if (!hasSpanishVoice && speechQueue.length > 0) {
        // Clear queue if no voice available
        speechQueue = [];
    }
}

/**
 * Internal function to speak text immediately (assumes voices are loaded)
 */
function speakTextNow(text, onComplete = null) {
    if (!speechEnabled || !hasSpanishVoice || !('speechSynthesis' in window)) {
        if (onComplete) onComplete();
        return;
    }

    speechSynthesis.cancel();

    currentUtterance = new SpeechSynthesisUtterance(text);

    if (onComplete) {
        currentUtterance.onend = onComplete;
        currentUtterance.onerror = onComplete;
    }

    // Use the selected voice
    if (selectedVoice) {
        currentUtterance.voice = selectedVoice;
        currentUtterance.lang = selectedVoice.lang;
    } else {
        currentUtterance.lang = 'es-MX';
    }

    currentUtterance.rate = speechRate;
    currentUtterance.pitch = 1.0;

    speechSynthesis.speak(currentUtterance);
}

/**
 * Speak text using the selected Spanish voice
 * If voices aren't loaded yet, queue the request
 */
function speakText(text, onComplete = null) {
    if (!speechEnabled || !hasSpanishVoice || !('speechSynthesis' in window)) {
        if (onComplete) onComplete();
        return;
    }

    if (!voicesLoaded) {
        // Queue this request until voices are ready
        console.log('Voices not loaded yet, queueing speech:', text.substring(0, 30) + '...');
        speechQueue.push({text, onComplete});
        return;
    }

    speakTextNow(text, onComplete);
}

/**
 * Update the speech toggle button text
 */
function updateSpeechToggleButton() {
    const menuToggleButton = document.getElementById('menu-speech-toggle');
    if (menuToggleButton) {
        if (!hasSpanishVoice) {
            menuToggleButton.textContent = '🔇 Audio: UNAVAILABLE';
        } else {
            menuToggleButton.textContent = speechEnabled ? '🔊 Audio: ON' : '🔇 Audio: OFF';
        }
    }
}

/**
 * Update the speech rate selector
 */
function updateSpeechRate() {
    const rateSelect = document.getElementById('speech-rate');
    if (rateSelect) {
        if (![0.7, 1.0, 1.2].includes(speechRate)) {
            speechRate = 1.0;
            localStorage.setItem('speechRate', speechRate);
        }
        rateSelect.value = speechRate.toFixed(1).toString();
    }
}

/**
 * Detect the user's operating system
 */
function detectOS() {
    const userAgent = navigator.userAgent || navigator.vendor || window.opera;

    if (/android/i.test(userAgent)) {
        return 'Android';
    }
    if (/iPad|iPhone|iPod/.test(userAgent) && !window.MSStream) {
        return 'iOS';
    }
    if (/Mac OS X/.test(userAgent)) {
        return 'macOS';
    }
    if (/Windows/.test(userAgent)) {
        // Try to detect Windows version
        if (/Windows NT 10/.test(userAgent)) {
            return 'Windows10/11';
        }
        return 'Windows';
    }
    return 'Unknown';
}

/**
 * Get OS-specific instructions for installing Spanish language pack
 */
function getInstallInstructions(os) {
    const instructions = {
        'Windows10/11': `
            <h3>Windows 10/11:</h3>
            <ol>
                <li>Open <strong>Settings</strong></li>
                <li>Go to <strong>Time & Language</strong></li>
                <li>Select <strong>Speech</strong></li>
                <li>Find the <strong>"Manage voices"</strong> section</li>
                <li>Click <strong>"Add voices"</strong></li>
                <li>Choose <strong>"Spanish (Mexico)"</strong> and click <strong>Add</strong></li>
                <li>Wait for the voice to download and install</li>
                <li>Close all browser windows and relaunch your browser</li>
            </ol>
        `,
        'macOS': `
            <h3>macOS:</h3>
            <ol>
                <li>Open <strong>System Settings</strong> (or <strong>System Preferences</strong> on older versions)</li>
                <li>Select <strong>Accessibility</strong></li>
                <li>Click on <strong>Spoken Content</strong></li>
                <li>Click on the <strong>System Voice</strong> dropdown</li>
                <li>Select <strong>Customize...</strong> (or <strong>Manage Voices...</strong>)</li>
                <li>Find and download a <strong>Spanish (Mexico)</strong> voice</li>
                <li><strong>"Paulina"</strong> or <strong>"Juan"</strong> are recommended</li>
                <li>Close all browser windows and relaunch your browser</li>
            </ol>
        `,
        'iOS': `
            <h3>iPhone/iPad:</h3>
            <ol>
                <li>Open <strong>Settings</strong></li>
                <li>Go to <strong>Accessibility</strong></li>
                <li>Select <strong>Spoken Content</strong></li>
                <li>Tap <strong>Voices</strong></li>
                <li>Select <strong>Spanish</strong></li>
                <li>Download a Mexican voice like <strong>"Mónica"</strong> or <strong>"Paulina"</strong></li>
                <li>Close all Safari tabs and relaunch Safari</li>
            </ol>
        `,
        'Android': `
            <h3>Android:</h3>
            <ol>
                <li>Open <strong>Settings</strong></li>
                <li>Go to <strong>System</strong> → <strong>Languages & input</strong></li>
                <li>Select <strong>Text-to-speech output</strong></li>
                <li>Tap the <strong>Settings</strong> icon next to the TTS engine</li>
                <li>Select <strong>Install voice data</strong></li>
                <li>Download <strong>Spanish (Mexico)</strong> or <strong>Spanish (Spain)</strong></li>
                <li>Close all Chrome tabs and relaunch Chrome</li>
            </ol>
        `
    };

    return instructions[os] || instructions['Windows10/11'];
}

/**
 * Detect the user's browser
 */
function detectBrowser() {
    const userAgent = navigator.userAgent;

    if (userAgent.indexOf('Edg') > -1) return 'Edge';
    if (userAgent.indexOf('Chrome') > -1) return 'Chrome';
    if (userAgent.indexOf('Safari') > -1) return 'Safari';
    if (userAgent.indexOf('Firefox') > -1) return 'Firefox';

    return 'Unknown';
}

/**
 * Show modal explaining how to get Spanish voices
 */
function showNoVoiceModal() {
    hasSeenModal = true;

    // Create modal HTML
    const os = detectOS();
    const browser = detectBrowser();
    const instructions = getInstallInstructions(os);

    const modalHTML = `
        <div id="no-voice-modal" lang="en" style="
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.8);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            box-sizing: border-box;
        ">
            <div style="
                background: white;
                border-radius: 12px;
                max-width: 700px;
                max-height: 90vh;
                overflow-y: auto;
                padding: 30px;
                box-shadow: 0 10px 50px rgba(0, 0, 0, 0.5);
            ">
                <h2 style="margin-top: 0; color: #c41e3a;">⚠️ No Spanish Voices Available</h2>

                <p>Your browser (<strong>${browser}</strong>) currently does not have access to any Spanish voices.</p>
                <p>The audio feature is optional. You can use the application without it, but audio <i>significantly helps</i> with pronunciation and learning.  This feature can be enabled and disabled at any time.</p>
                <p>However, in order to utilize this feature, you will need to do one of the following:</p>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">

                <h3>Option 1: Switch to Chrome or Edge</h3>
                <p><strong>Google Chrome</strong> and <strong>Microsoft Edge</strong> include built-in Spanish voices and work immediately without additional configuration.</p>

                <div style="margin: 15px 0;">
                    <a href="https://www.google.com/chrome/" target="_blank" style="
                        display: inline-block;
                        background-color: #0078d4;
                        color: white;
                        padding: 10px 20px;
                        border-radius: 5px;
                        text-decoration: none;
                        margin-right: 10px;
                    ">Download Chrome</a>

                    <a href="https://www.microsoft.com/edge" target="_blank" style="
                        display: inline-block;
                        background-color: #0078d4;
                        color: white;
                        padding: 10px 20px;
                        border-radius: 5px;
                        text-decoration: none;
                    ">Download Edge</a>
                </div>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">

                <h3>Option 2: Install Spanish Language Pack</h3>
                <p>You can also install Spanish voices on your current operating system:</p>

                ${instructions}
                
                <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">

                <p style="font-size: 0.9em; color: #666;">
                    <strong>Note:</strong> Clicking on the "Audio: UNAVAILABLE" button (on the top right of most pages) will display this notice again should you need these instructions later.
                </p>

                <div style="margin-top: 25px; text-align: center;">
                    <button id="close-voice-modal" style="
                        background-color: #005a31;
                        color: white;
                        border: none;
                        padding: 12px 30px;
                        font-size: 1em;
                        border-radius: 5px;
                        cursor: pointer;
                    ">Got It - Close</button>
                </div>
            </div>
        </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHTML);

    // Add close button handler
    document.getElementById('close-voice-modal').addEventListener('click', function() {
        document.getElementById('no-voice-modal').remove();
        localStorage.setItem('hasSeenVoiceModal', 'true');
        hasSeenModal = true;
    });

    // Also allow clicking outside modal to close
    document.getElementById('no-voice-modal').addEventListener('click', function(e) {
        if (e.target.id === 'no-voice-modal') {
            document.getElementById('no-voice-modal').remove();
            localStorage.setItem('hasSeenVoiceModal', 'true');
            hasSeenModal = true;
        }
    });
}

/**
 * Initialize speech functionality
 */
function initializeSpeech() {
    // Prevent multiple initializations
    if (isInitialized) {
        return;
    }
    isInitialized = true;

    // Load voices immediately (try synchronously first)
    loadVoices();

    // Also set up listener for when voices change (async loading)
    if (speechSynthesis.onvoiceschanged !== undefined) {
        speechSynthesis.onvoiceschanged = loadVoices;
    }

    // Force a check after a short delay to ensure voices are loaded
    setTimeout(loadVoices, 100);

    // Update UI
    updateSpeechToggleButton();
    updateSpeechRate();

    // Setup event listeners
    const menuToggleButton = document.getElementById('menu-speech-toggle');
    if (menuToggleButton) {
        menuToggleButton.addEventListener('click', () => {
            if (!hasSpanishVoice) {
                // Show modal if trying to enable when no voice available
                showNoVoiceModal();
                return;
            }

            speechEnabled = !speechEnabled;
            localStorage.setItem('speechEnabled', speechEnabled);
            updateSpeechToggleButton();
            if (!speechEnabled) {
                speechSynthesis.cancel();
            }
        });
    }

    const rateSelect = document.getElementById('speech-rate');
    if (rateSelect) {
        rateSelect.addEventListener('change', (e) => {
            speechRate = parseFloat(e.target.value);
            localStorage.setItem('speechRate', speechRate);
        });
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeSpeech);
} else {
    // DOM is already ready, initialize immediately
    initializeSpeech();
}
