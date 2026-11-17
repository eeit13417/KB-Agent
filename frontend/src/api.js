const BASE = "/api";

export async function login(email, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    body: new URLSearchParams({ username: email, password }),
  });
  if (!res.ok) throw new Error("Incorrect email or password.");
  return (await res.json()).access_token;
}

export async function register(email, password) {
  const res = await fetch(`${BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Registration failed.");
  }
  return (await res.json()).access_token;
}

export async function streamChat(token, question, { onCitations, onToken }) {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) throw new Error(res.status === 401 ? "Your session has expired. Please log in again." : "Server error.");

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += value;
    const parts = buffer.split("\n\n");
    // The last part may be half an event; keep it until the rest arrives.
    buffer = parts.pop();

    for (const part of parts) {
      if (!part.startsWith("data: ")) continue;
      const event = JSON.parse(part.slice(6));
      if (event.type === "citations") onCitations(event.items);
      if (event.type === "token") onToken(event.text);
    }
  }
}
