import { useEffect, useRef, useState } from "react";
import { streamChat } from "./api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";


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

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">勞動法規問答</span>
        <button className="link" onClick={onLogout}>登出</button>
      </header>

      <main className="layout">
        <section className="conversation">
          <div className="messages">
            {messages.length === 0 && <p className="empty">試著問：「特別休假怎麼計算？」</p>}

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
              placeholder="輸入你的問題…"
              disabled={busy}
            />
            <button type="submit" disabled={busy || !input.trim()}>送出</button>
          </form>
        </section>

        <aside className="sources">
          <h2>參考來源</h2>
          {citations.length === 0 && <p className="muted">送出問題後，這裡會列出引用的條文。</p>}

          {citations.map((citation) => (
            <a
              key={`${citation.title}-${citation.article_no}`}
              className="source-card"
              href={citation.source_url}
              target="_blank"
              rel="noreferrer"
            >
              <span className="source-title">{citation.title}</span>
              <span className="source-article">{citation.article_no}</span>
              {citation.chapter && <span className="source-chapter">{citation.chapter}</span>}
              <span className="source-score">距離 {citation.distance.toFixed(3)}</span>
            </a>
          ))}
        </aside>
      </main>
    </div>
  );
}
