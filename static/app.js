const chat = document.getElementById("chat");
const statusEl = document.getElementById("status");
const progressBar = document.getElementById("progressBar");

function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function setStatus(text, progress) {
  statusEl.textContent = text || "";
  if (progress === null || progress === undefined) return;
  progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

function formatFinal(finalData) {
  const cls = finalData.classification;
  let out = `✅ Classification:\n- Category: ${cls.category}\n- Intent: ${cls.intent}\n- Confidence: ${cls.confidence}\n- Reasoning: ${cls.reasoning}\n`;

  if (finalData.sales) {
    out += `\n🧾 Sales Ticket: ${finalData.sales.ticket_id}\n${finalData.sales.message_to_rep}\n`;

    if (finalData.sales.recommendations?.length) {
      out += `\n📦 Recommendations:\n`;
      finalData.sales.recommendations.forEach((r, i) => {
        out += `  ${i+1}) ${r.name} (${r.sku}) - $${r.price_usd}\n     Purpose: ${r.purpose}\n     Score: ${r.score}\n     Reason: ${r.reasoning}\n`;
      });
    }

    if (finalData.sales.bundles?.length) {
      out += `\n🎁 Bundle Options (sorted by price):\n`;
      finalData.sales.bundles.forEach((b, i) => {
        out += `  ${i+1}) ${b.name} - $${b.total_price_usd}\n     Items: ${b.items.join(", ")}\n     Score: ${b.score}\n     Reason: ${b.reasoning}\n`;
      });
    }

    if (finalData.sales.follow_up_questions?.length) {
      out += `\n❓ Follow-up Questions:\n`;
      finalData.sales.follow_up_questions.forEach((q, i) => {
        out += `  ${i+1}) ${q}\n`;
      });
    }
  }

  if (finalData.support) {
    out += `\n🛠 Support Ticket: ${finalData.support.ticket_id}\n${finalData.support.message_to_rep}\n`;
    if (finalData.support.follow_up_questions?.length) {
      out += `\n❓ Follow-up Questions:\n`;
      finalData.support.follow_up_questions.forEach((q, i) => {
        out += `  ${i+1}) ${q}\n`;
      });
    }
  }
  return out;
}

document.getElementById("sendBtn").addEventListener("click", async () => {
  const subject = document.getElementById("subject").value.trim();
  const body = document.getElementById("body").value.trim();
  const files = document.getElementById("attachments").files;

  if (!subject || !body) {
    addBubble("assistant", "Please provide both subject and email body.");
    return;
  }

  addBubble("user", `Subject: ${subject}\n\n${body}`);
  setStatus("Starting workflow...", 0);

  const fd = new FormData();
  fd.append("subject", subject);
  fd.append("body", body);
  for (const f of files) fd.append("attachments", f);

  const res = await fetch("/api/start", { method: "POST", body: fd });
  const payload = await res.json();
  const run_id = payload.run_id;

  const es = new EventSource(`/api/stream/${run_id}`);

  es.addEventListener("status", (e) => {
    const data = JSON.parse(e.data);
    const msg = data.message;
    const step = data.step || "processing";
    const progress = data.progress;
    setStatus(`[${step}] ${msg}`, progress);
  });

  es.addEventListener("final", (e) => {
    const data = JSON.parse(e.data);
    addBubble("assistant", formatFinal(data.data));
    setStatus("Done.", 100);
    es.close();
  });

  es.addEventListener("error", (e) => {
    try {
      const data = JSON.parse(e.data);
      addBubble("assistant", `❌ Error: ${data.message}`);
    } catch {
      addBubble("assistant", `❌ Error: Streaming failed.`);
    }
    setStatus("Failed.", 0);
    es.close();
  });
});
