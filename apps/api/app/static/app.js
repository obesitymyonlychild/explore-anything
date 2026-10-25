async function showHealth() {
  const list = document.getElementById("health");
  try {
    const res = await fetch("/api/health");
    const h = await res.json();
    list.innerHTML = `
      <li>Database: ${h.db ? "ok" : "unreachable"}</li>
      <li>Anthropic API key: ${h.anthropic_api_key ? "set" : "missing (needed from M2)"}</li>`;
  } catch {
    list.innerHTML = "<li>API unreachable</li>";
  }
}

showHealth();
