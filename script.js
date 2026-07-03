function encodeFormData(form) {
  const data = new FormData(form);
  return new URLSearchParams(data).toString();
}

const form = document.getElementById("waitlist-form");
const errorEl = document.getElementById("form-error");
const successEl = document.getElementById("success-message");

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.style.display = "none";

    const submitBtn = form.querySelector("button[type='submit']");
    submitBtn.disabled = true;
    submitBtn.textContent = "Joining...";

    try {
      const response = await fetch("/", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: encodeFormData(form),
      });

      if (!response.ok) {
        throw new Error("Network response was not ok");
      }

      form.style.display = "none";
      successEl.style.display = "block";
    } catch (err) {
      errorEl.style.display = "block";
      submitBtn.disabled = false;
      submitBtn.textContent = "Join the waitlist";
    }
  });
}
