// --- START OF FILE my-python-app/static/js/seat-selection.js ---

document.addEventListener('DOMContentLoaded', () => {
    const seatMapContainer = document.getElementById('seat-map-container');
    if (!seatMapContainer) return;

    // --- Data Attributes ---
    const showtimeId = seatMapContainer.dataset.showtimeId;
    const layout = JSON.parse(seatMapContainer.dataset.layout);
    const prices = {
        standard: parseFloat(seatMapContainer.dataset.priceStandard),
        premium: parseFloat(seatMapContainer.dataset.pricePremium),
        vip: parseFloat(seatMapContainer.dataset.priceVip)
    };

    // --- DOM Elements ---
    const selectedCountEl = document.getElementById('selected-count');
    const selectedTotalEl = document.getElementById('selected-total');
    const payButton = document.getElementById('pay-button'); // This is now the "Continue" button

    // This state variable will hold the selected seats. Using your original array approach.
    let selectedSeats = [];

    // --- Functions ---

    /**
     * Renders the seat map based on the layout data.
     * (No changes needed here from your original code)
     */
    function renderSeatMap() {
        layout.forEach((row, rowIndex) => {
            const rowEl = document.createElement('div');
            rowEl.classList.add('seat-row');
            row.forEach((seatCode, colIndex) => {
                const seatEl = document.createElement('button');
                seatEl.classList.add('seat');
                let seatType = 'standard';
                let price = prices.standard;

                // Determine seat type and price based on the code from the server
                if (seatCode === 2 || seatCode === 3) { // Premium
                    seatType = 'premium';
                    price = prices.premium;
                } else if (seatCode === 4 || seatCode === 5) { // VIP
                    seatType = 'vip';
                    price = prices.vip;
                }

                seatEl.classList.add(seatType);

                // Mark booked seats as disabled
                if (seatCode % 2 !== 0) {
                    seatEl.classList.add('booked');
                    seatEl.disabled = true;
                }

                seatEl.dataset.row = rowIndex;
                seatEl.dataset.col = colIndex;
                seatEl.dataset.price = price;
                seatEl.dataset.type = seatType;

                seatEl.addEventListener('click', toggleSeatSelection);
                rowEl.appendChild(seatEl);
            });
            seatMapContainer.appendChild(rowEl);
        });
    }

    /**
     * Handles the click event on a seat to select or deselect it.
     * (No changes needed here from your original code)
     */
    function toggleSeatSelection(event) {
        const seat = event.target;
        if (seat.classList.contains('booked')) return;

        seat.classList.toggle('selected');
        const seatIdentifier = `${seat.dataset.row}-${seat.dataset.col}`;

        if (seat.classList.contains('selected')) {
            // Add to selection
            selectedSeats.push({
                row: parseInt(seat.dataset.row),
                col: parseInt(seat.dataset.col),
                price: parseFloat(seat.dataset.price),
                type: seat.dataset.type,
                identifier: seatIdentifier
            });
        } else {
            // Remove from selection
            selectedSeats = selectedSeats.filter(s => s.identifier !== seatIdentifier);
        }
        updateSummary();
    }

    /**
     * Updates the booking summary and enables/disables the continue button.
     */
    function updateSummary() {
        const count = selectedSeats.length;
        const total = selectedSeats.reduce((sum, seat) => sum + seat.price, 0);

        selectedCountEl.textContent = count;
        selectedTotalEl.textContent = total.toFixed(2);

        // Enable the button only if at least one seat is selected
        payButton.disabled = count === 0;
    }

    /**
     * NEW: Sends selected seat data to the server to start the booking process
     * and redirects to the food selection page. This function replaces your old processPayment.
     */
    async function proceedToFoodSelection() {
        if (selectedSeats.length === 0) {
            alert('Please select at least one seat to continue.');
            return;
        }

        payButton.disabled = true;
        payButton.innerHTML = '<span class="loading"></span> Please Wait...';

        // Prepare data to send to the new '/booking/start' endpoint
        const bookingStartData = {
            showtime_id: showtimeId,
            seats: selectedSeats.map(s => ({ row: s.row, col: s.col, type: s.type, price: s.price })),
            total_price: parseFloat(selectedTotalEl.textContent)
        };

        try {
            const response = await fetch('/booking/start', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(bookingStartData),
            });

            const result = await response.json();

            if (result.success && result.redirect_url) {
                // If successful, redirect to the URL provided by the server
                window.location.href = result.redirect_url;
            } else {
                alert(`Error: ${result.message || 'Could not proceed. Please try again.'}`);
                // Re-enable button on failure
                payButton.disabled = false;
                payButton.innerHTML = 'Continue to Snacks';
            }
        } catch (error) {
            console.error('Failed to start booking:', error);
            alert('An error occurred. Please check the console and try again.');
            payButton.disabled = false;
            payButton.innerHTML = 'Continue to Snacks';
        }
    }

    // --- Initializations ---
    renderSeatMap();
    
    // The button click now triggers the new function to go to the food page
    payButton.addEventListener('click', proceedToFoodSelection);
});