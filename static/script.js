
const form = document.getElementById("transferForm");

if (form) {

    const message = document.getElementById("message");

    const button = document.getElementById("transferButton");

    const csrfToken = document.querySelector(
        'meta[name="csrf-token"]'
    ).content;

    // One key for each payment attempt.
    // Keep the same key if the request needs retrying.

    let idempotencyKey = crypto.randomUUID();


    form.addEventListener("submit", async function(event) {

        event.preventDefault();

        if (button.disabled) {
            return;
        }

        const receiver = document.getElementById(
            "receiver"
        ).value.trim();

        const amount = document.getElementById(
            "amount"
        ).value;

        button.disabled = true;

        button.innerText = "Processing...";

        message.innerText = "";

        message.className = "";


        try {

            const response = await fetch("/api/transfer", {

                method: "POST",

                headers: {

                    "Content-Type": "application/json",

                    "X-CSRFToken": csrfToken,

                    "Idempotency-Key": idempotencyKey

                },

                body: JSON.stringify({

                    receiver_email: receiver,

                    amount: amount

                })

            });


            const result = await response.json();

            if (response.ok) {

                message.innerText = result.message;

                message.className = "success";

                // A new key is generated only after success.
                idempotencyKey = crypto.randomUUID();

                form.reset();

                setTimeout(() => {

                    window.location.reload();

                }, 1000);

            } else {

                message.innerText =
                    result.error || "Payment failed.";

                message.className = "error";

            }

        } catch (error) {

            // Retain the same key for a possible retry.

            message.innerText =
                "Network error. Please retry the same payment.";

            message.className = "error";

        } finally {

            button.disabled = false;

            button.innerText = "Transfer Money";

        }

    });

}
