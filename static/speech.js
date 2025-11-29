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
        // Save the voice name for consistency across pages
        localStorage.setItem('selectedVoiceName', spanishVoice.name);
        console.log('Selected Spanish voice:', spanishVoice.name, '(' + spanishVoice.lang + ')');
    } else {
        console.warn('No Spanish voice found, will use browser default');
        voicesLoaded = true; // Still mark as loaded even if no voice found
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

    // Process any queued speech requests
    if (voicesLoaded && speechQueue.length > 0) {
        console.log('Processing', speechQueue.length, 'queued speech requests');
        while (speechQueue.length > 0) {
            const {text, onComplete} = speechQueue.shift();
            speakTextNow(text, onComplete);
        }
    }
}

/**
 * Internal function to speak text immediately (assumes voices are loaded)
 */
function speakTextNow(text, onComplete = null) {
    if (!speechEnabled || !('speechSynthesis' in window)) {
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
    if (!speechEnabled || !('speechSynthesis' in window)) {
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
        menuToggleButton.textContent = speechEnabled ? '🔊 Audio: ON' : '🔇 Audio: OFF';
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
        rateSelect.value = speechRate.toString();
    }
}

/**
 * Initialize speech functionality
 */
function initializeSpeech() {
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

// Initialize immediately if possible
initializeSpeech();

// Also initialize when DOM is ready (if we loaded before DOM)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeSpeech);
}
