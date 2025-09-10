// static/js/utils.js

/**
 * Escapes HTML special characters in a string.
 * @param {string} str The string to escape.
 * @returns {string} The escaped string.
 */
const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));

/**
 * Fetches and displays weather for a given location and date.
 * @param {HTMLElement} widget The container element to display the weather in.
 */
async function fetchWeather(widget) {
    if (!widget) return;

    const location = widget.dataset.location;
    const date = widget.dataset.date;

    widget.innerHTML = '<p><em>Fetching weather...</em></p>';

    if (!location) {
        widget.innerHTML = '<p class="text-muted">No location set.</p>';
        return;
    }
    if (!date) {
        widget.innerHTML = '<p class="text-danger">Error: Date is missing.</p>';
        return;
    }

    const today = new Date().toISOString().split('T')[0];
    const isToday = date.startsWith(today);
    const url = isToday ? `/api/weather/${encodeURIComponent(location)}` : `/api/weather/${encodeURIComponent(location)}?date=${date}`;

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Server responded with status: ${response.status}`);
        const weather = await response.json();

        const tempDisplay = isToday ? weather.current_temp : `High/Low: ${weather.high_temp} / ${weather.low_temp}`;
        widget.innerHTML = `
            <p><strong>${isToday ? 'Current' : 'Forecast'}:</strong> ${tempDisplay || 'N/A'}<br>
               <strong>Wind:</strong> ${weather.wind || 'N/A'}<br>
               <strong>Precipitation:</strong> ${weather.precipitation || 'N/A'}</p>`;
    } catch (error) {
        widget.innerHTML = `<p class="text-danger">Could not load weather data.</p>`;
        console.error('Weather fetch error:', error);
    }
}
