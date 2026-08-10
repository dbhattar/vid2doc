type Testimonial = { quote: string; name: string; role: string | null };

const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';

const section = document.getElementById('testimonials');
const grid = document.getElementById('testimonial-grid');

if (section && grid) {
  fetch(`${API_URL}/api/public/testimonials`)
    .then((res) => {
      if (!res.ok) throw new Error(res.statusText);
      return res.json();
    })
    .then((data: { testimonials: Testimonial[] }) => {
      if (!data.testimonials || data.testimonials.length === 0) return;

      for (const [i, t] of data.testimonials.entries()) {
        const card = document.createElement('blockquote');
        card.className = i === 0 ? 'testimonial-card testimonial-card--accent' : 'testimonial-card';

        const quote = document.createElement('p');
        quote.className = 'testimonial-quote';
        quote.textContent = `“${t.quote}”`;
        card.appendChild(quote);

        const footer = document.createElement('footer');
        const name = document.createElement('span');
        name.className = 'testimonial-name';
        name.textContent = t.name;
        footer.appendChild(name);
        if (t.role) {
          const role = document.createElement('span');
          role.className = 'testimonial-role';
          role.textContent = t.role;
          footer.appendChild(role);
        }
        card.appendChild(footer);

        grid.appendChild(card);
      }

      // Hidden by default (see Testimonials.astro) -- only revealed once we
      // know there's at least one real testimonial to show, per "hide the
      // section if there are none" rather than showing it empty.
      section.hidden = false;
    })
    .catch(() => {
      // No API reachable / request failed -- stay hidden, same as "no
      // testimonials yet". Not worth surfacing an error for a marketing
      // section.
    });
}
