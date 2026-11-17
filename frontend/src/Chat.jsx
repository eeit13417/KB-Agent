import { useEffect, useRef, useState } from "react";
import { streamChat } from "./api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Pieces of one long section share a label; list each section once, at its best rank.
// The server sends citations sorted by distance, so the first one seen is the closest.
function uniqueSources(citations) {
  const seen = new Set();
  return citations.filter((citation) => {
    const key = `${citation.title} ${citation.article_no}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default function Chat({ token, onLogout }) {
  const [messages, setMessages] = useState([]);
  const [citations, setCitations] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(event) {
    event.preventDefault();
    const question = input.trim();
    if (!question || busy) return;

    setInput("");
    setBusy(true);
    setCitations([]);
    setMessages((prev) => [...prev, { role: "user", text: question }, { role: "assistant", text: "" }]);

    try {
      await streamChat(token, question, {
        onCitations: setCitations,
        onToken: (text) =>
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, text: last.text + text };
            return next;
          }),
      });
    } catch (err) {
      setMessages((prev) => [...prev, { role: "error", text: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  const sources = uniqueSources(citations);

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">US Labor Law Assistant</span>
        <button className="link" onClick={onLogout}>Log out</button>
      </header>

      <main className="layout">
        <section className="conversation">
          <div className="messages">
            {messages.length === 0 && <p className="empty">Try asking: "Do I get paid for sleeping time during a 24-hour shift?"</p>}

            {messages.map((message, index) => (
              <div key={index} className={`bubble ${message.role}`}>
                {message.role === "assistant" ? (
                  message.text ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
                  ) : (
                    <span className="typing">···</span>
                  )
                ) : (
                  message.text
                )}
              </div>
            ))}


            <div ref={bottomRef} />
          </div>

          <form className="composer" onSubmit={send}>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask a question…"
              disabled={busy}
            />
            <button type="submit" disabled={busy || !input.trim()}>Send</button>
          </form>
        </section>

        <aside className="sources">
          <h2>Sources</h2>
          {sources.length === 0 && <p className="muted">Regulations used for the answer will appear here.</p>}

          {sources.map((citation) => (
            <a
              key={`${citation.title} ${citation.article_no}`}
              className="source-card"
              href={citation.source_url}
              target="_blank"
              rel="noreferrer"
            >
              <span className="source-title">{citation.title}</span>
              <span className="source-article">{citation.article_no}</span>
              {citation.chapter && <span className="source-chapter">{citation.chapter}</span>}
              <span className="source-score">distance {citation.distance.toFixed(3)}</span>
            </a>
          ))}
        </aside>
      </main>
    </div>
  );
}
