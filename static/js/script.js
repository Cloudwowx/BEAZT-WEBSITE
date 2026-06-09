// ============================================
// BeaZt Cheats 2026 — Ambient Orbs Background
// ============================================

(function () {
  const canvas = document.getElementById("ambient-canvas");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  const orbs = [
    { x: 0.22, y: 0.18, r: 300, dx: 0.00015, dy: 0.00012, c: "79,110,246" },
    { x: 0.78, y: 0.72, r: 260, dx: -0.0001, dy: -0.00014, c: "139,92,246" },
    { x: 0.50, y: 0.40, r: 350, dx: 0.00008, dy: -0.0001, c: "79,110,246" },
    { x: 0.85, y: 0.22, r: 220, dx: -0.00012, dy: 0.00008, c: "55,110,230" },
  ];

  function draw() {
    ctx.clearRect(0, 0, width, height);

    orbs.forEach(function (o) {
      o.x += o.dx;
      o.y += o.dy;
      if (o.x > 1.1 || o.x < -0.1) o.dx *= -1;
      if (o.y > 1.1 || o.y < -0.1) o.dy *= -1;

      const cx = o.x * width;
      const cy = o.y * height;

      const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, o.r);
      gradient.addColorStop(0, `rgba(${o.c},0.10)`);
      gradient.addColorStop(0.4, `rgba(${o.c},0.04)`);
      gradient.addColorStop(0.7, `rgba(${o.c},0.01)`);
      gradient.addColorStop(1, "rgba(8,11,22,0)");

      ctx.fillStyle = gradient;
      ctx.fillRect(cx - o.r, cy - o.r, o.r * 2, o.r * 2);
    });

    requestAnimationFrame(draw);
  }
  draw();

  window.addEventListener("resize", function () {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  // ScrollReveal
  if (typeof ScrollReveal !== "undefined") {
    ScrollReveal().reveal(".reveal", {
      distance: "36px",
      origin: "bottom",
      opacity: 0,
      duration: 700,
      easing: "cubic-bezier(0.25, 0.46, 0.45, 0.94)",
      interval: 50,
      cleanup: true,
    });
  }

  // Flash auto-dismiss
  document.querySelectorAll(".flash-message").forEach(function (msg) {
    setTimeout(function () {
      msg.style.opacity = "0";
      msg.style.transform = "translateX(16px)";
      msg.style.transition = "all 0.3s ease";
      setTimeout(function () { msg.remove(); }, 300);
    }, 4500);
  });

  // Stats counter
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
              var suffix = text.substring(
                text.indexOf(String(target)) + String(target).length
              );
              var current = 0;
              var steps = 30;
              var increment = target / steps;
              var stepTime = 1000 / steps;
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
    statValues.forEach(function (el) { observer.observe(el); });
  }
})();
