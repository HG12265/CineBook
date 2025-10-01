// Enhanced seat selection - CineBook
document.addEventListener('DOMContentLoaded', function() {
    console.log("CineBook script loaded...");
    
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });
    
    // Mobile menu handling
    const navbarToggler = document.querySelector('.navbar-toggler');
    const navbarCollapse = document.querySelector('.navbar-collapse');

    if (navbarToggler && navbarCollapse) {
        console.log("Navbar toggler and collapse found. Adding click listener.");
        navbarToggler.addEventListener('click', function() {
            const isExpanded = this.getAttribute('aria-expanded') === 'true' || false; // Get current state
            navbarCollapse.classList.toggle('show');
            this.setAttribute('aria-expanded', !isExpanded); // Toggle aria-expanded attribute
            console.log("Navbar toggled. Collapse has 'show' class:", navbarCollapse.classList.contains('show'));
        });
    } else {
        console.warn("Navbar toggler or collapse not found. Mobile menu handling not initialized.");
    }
    
    // Seat selection code
    const seats = document.querySelectorAll('.seat');
    const bookingForm = document.getElementById('booking-form');
    
    if (seats.length > 0 && bookingForm) {
        console.log("Seat selection initializing...");
        
        const selectedSeats = [];
        const seatsInput = bookingForm.querySelector('input[name="seats"]');
        const submitButton = bookingForm.querySelector('button[type="submit"]');
        const selectedSeatsContainer = document.getElementById('selected-seats');
        const priceSummary = document.getElementById('price-summary');
        
        seats.forEach(seat => {
            if (!seat.classList.contains('booked')) {
                seat.addEventListener('click', function() {
                    const row = this.dataset.row;
                    const col = this.dataset.col;
                    const seatId = `${row},${col}`;
                    
                    if (this.classList.contains('selected')) {
                        // Deselect seat
                        this.classList.remove('selected');
                        const index = selectedSeats.findIndex(s => s.id === seatId);
                        if (index !== -1) {
                            selectedSeats.splice(index, 1);
                        }
                    } else {
                        // Select seat
                        this.classList.add('selected');
                        
                        // Determine seat type
                        let type = 'Standard';
                        if (this.classList.contains('premium')) type = 'Premium';
                        if (this.classList.contains('vip')) type = 'VIP';
                        
                        // Get price from data attributes or use defaults
                        let price = 100.0;
                        if (this.dataset.price) {
                            price = parseFloat(this.dataset.price);
                        } else {
                            if (type === 'Premium') price = 150.0;
                            if (type === 'VIP') price = 200.0;
                        }
                        
                        selectedSeats.push({
                            id: seatId,
                            row: parseInt(row),
                            col: parseInt(col),
                            type: type,
                            price: price
                        });
                    }
                    
                    updateBookingSummary();
                });
            }
        });
        
        function updateBookingSummary() {
            // Update selected seats display
            if (selectedSeats.length === 0) {
                selectedSeatsContainer.innerHTML = '<p class="mb-1 text-muted">No seats selected</p>';
            } else {
                let html = '<h6>Selected Seats:</h6>';
                selectedSeats.forEach(seat => {
                    html += `<div class="d-flex justify-content-between mb-1">
                        <span>Row ${seat.row + 1}, Seat ${seat.col + 1} (${seat.type})</span>
                        <span>₹${seat.price.toFixed(2)}</span>
                    </div>`;
                });
                selectedSeatsContainer.innerHTML = html;
            }
            
            // Update price summary
            const subtotal = selectedSeats.reduce((sum, seat) => sum + seat.price, 0);
            
            priceSummary.innerHTML = `
                <div class="d-flex justify-content-between mb-1">
                    <span>Subtotal:</span>
                    <span>₹${subtotal.toFixed(2)}</span>
                </div>
                <hr>
                <div class="d-flex justify-content-between fw-bold">
                    <span>Total:</span>
                    <span>₹${subtotal.toFixed(2)}</span>
                </div>
            `;
            
            // Update form data and button state
            seatsInput.value = JSON.stringify(selectedSeats.map(seat => ({
                row: seat.row,
                col: seat.col
            })));
            
            submitButton.disabled = selectedSeats.length === 0;
        }
        
        // Handle form submission
        bookingForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            if (selectedSeats.length === 0) {
                alert('Please select at least one seat');
                return;
            }
            
            const formData = new FormData(this);
            
            fetch('/book', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.location.href = '/booking-confirmation/' + data.booking_id;
                } else {
                    alert('Error: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An error occurred while booking tickets');
            });
        });
    }
    
    // Rating stars interaction
    const ratingInputs = document.querySelectorAll('.rating input');
    ratingInputs.forEach(input => {
        input.addEventListener('change', function() {
            const rating = this.value;
            const labels = this.parentElement.querySelectorAll('label');
            
            labels.forEach((label, index) => {
                if (index < rating) {
                    label.querySelector('i').classList.add('bi-star-fill');
                    label.querySelector('i').classList.remove('bi-star');
                } else {
                    label.querySelector('i').classList.add('bi-star');
                    label.querySelector('i').classList.remove('bi-star-fill');
                }
            });
        });
    });
});