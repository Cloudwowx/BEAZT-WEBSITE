// ============================================
// BeaZt Cheats 2026 — Code Stream Canvas + Animations
// ============================================

(function () {
  // ---- Code Stream Canvas ----
  const canvas = document.getElementById("code-canvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const snippets = [
      "function init() {",
      "  const data = [];",
      "  for (let i = 0; i < n; i++) {",
      "    data.push(i * 2);",
      "  }",
      "  return data;",
      "}",
      "async function fetch() {",
      "  const res = await api.get();",
      "  return res.json();",
      "}",
      "class Controller {",
      "  constructor(opts) {",
      "    this.state = opts;",
      "  }",
      "  mount() {",
      "    this.render();",
      "  }",
      "}",
      "const config = {",
      '  "mode": "production",',
      '  "debug": false,',
      '  "version": "2.0"',
      "};",
      "export default {",
      "  plugins: [vue(), react()],",
      "  server: { port: 3000 }",
      "};",
      "SELECT * FROM users",
      "WHERE active = true",
      "ORDER BY created_at DESC;",
      'GET /api/v1/session',
      "Host: beazt.cheats",
      "Authorization: Bearer ...",
      "import { createApp } from 'vue';",
      "import { StrictMode } from 'react';",
      "fn main() {",
      "    println!(\"Hello\");",
      "}",
      "def handle(req):",
      "    key = generate_key()",
      "    return key, 200",
      "0x7F 0x45 0x4C 0x46 0x02 0x01 0x01",
      "BEAZT-4F2A-9C1D-E873",
      "{ } [ ] ( ) => . , ; :",
      "/* beazt.module.css */",
      "#container {",
      "  display: flex;",
      "  background: #060A14;",
      "}",
      "npm install beazt-sdk",
      "docker compose up -d",
      "git push origin main",
      "ws://localhost:5000",
    ];

    const fontSize = 13;
    const columns = Math.floor(width / (fontSize * 6));
    const drops = [];
    for (let i = 0; i < columns; i++) {
      drops[i] = {
        y: Math.random() * -height,
        speed: Math.random() * 0.35 + 0.15,
        snippet: snippets[Math.floor(Math.random() * snippets.length)],
        x: i * (fontSize * 6) + Math.random() * 40,
        alpha: Math.random() * 0.4 + 0.3,
      };
    }

    function draw() {
      ctx.fillStyle = "rgba(6, 10, 20, 0.04)";
      ctx.fillRect(0, 0, width, height);

      ctx.font = `${fontSize}px "JetBrains Mono", "Fira Code", monospace`;

      drops.forEach(function (d) {
        const y = d.y;
        const x = d.x;

        // Leading character (brightest)
        ctx.fillStyle = `rgba(96, 165, 250, ${d.alpha * 1.6})`;
        ctx.fillText(d.snippet, x, y);

        // Trailing blur characters
        for (let t = 1; t <= 8; t++) {
          const ta = Math.max(0, d.alpha * (0.7 - t * 0.08));
          ctx.fillStyle = `rgba(59, 130, 246, ${ta})`;
          ctx.fillText(
            snippets[Math.floor(Math.random() * snippets.length)],
            x,
            y - t * fontSize * 1.4
          );
        }

        d.y += d.speed;
        if (d.y > height + 100) {
          d.y = Math.random() * -200;
          d.x = Math.floor(Math.random() * columns) * (fontSize * 6) + Math.random() * 40;
          d.snippet = snippets[Math.floor(Math.random() * snippets.length)];
          d.speed = Math.random() * 0.35 + 0.15;
        }
      });

      requestAnimationFrame(draw);
    }
    draw();

    window.addEventListener("resize", function () {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });
  }

  // ---- ScrollReveal (always runs, not gated by canvas) ----
  if (typeof ScrollReveal !== "undefined") {
    ScrollReveal().reveal(".reveal", {
      distance: "40px",
      origin: "bottom",
      opacity: 0,
      duration: 800,
      easing: "cubic-bezier(0.25, 0.46, 0.45, 0.94)",
      interval: 60,
      cleanup: true,
    });
  }

  // ---- Flash message auto-dismiss ----
  document.querySelectorAll(".flash-message").forEach(function (msg) {
    setTimeout(function () {
      msg.style.opacity = "0";
      msg.style.transform = "translateX(16px)";
      msg.style.transition = "all 0.3s ease";
      setTimeout(function () { msg.remove(); }, 300);
    }, 4500);
  });

  // ---- Magnetic hover on buttons ----
  document.querySelectorAll(".btn-primary, .pricing-card").forEach(function (el) {
    el.addEventListener("mousemove", function (e) {
      var rect = el.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var mx = (x / rect.width) * 100;
      el.style.setProperty("--mx", mx + "%");
    });
    el.addEventListener("mouseleave", function () {
      el.style.setProperty("--mx", "50%");
    });
  });

  // ---- Stats counter animation ----
  var statValues = document.querySelectorAll(".stat-value");
  if (statValues.length && typeof IntersectionObserver !== "undefined") {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            var el = entry.target;
            var text = el.textContent.trim();
            var nums = text.match(/\d+/g);
            if (nums && nums.length > 0) {
              var target = parseInt(nums[0], 10);
              var prefix = text.substring(0, text.indexOf(String(target)));
              var suffix = text.substring(text.indexOf(String(target)) + String(target).length);
              var current = 0;
              var duration = 1000;
              var steps = 30;
              var increment = target / steps;
              var stepTime = duration / steps;
              var timer = setInterval(function () {
                current += increment;
                if (current >= target) {
                  el.textContent = prefix + target + suffix;
                  clearInterval(timer);
                } else {
                  el.textContent = prefix + Math.floor(current) + suffix;
                }
              }, stepTime);
            }
            observer.unobserve(el);
          }
        });
      },
      { threshold: 0.5 }
    );
    statValues.forEach(function (el) {
      observer.observe(el);
    });
  }
})();
