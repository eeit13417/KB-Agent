import { useState } from "react";
import { login, register } from "./api";

export default function Login({ onAuth }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(action) {
    setBusy(true);
    setError("");
    try {
      onAuth(await action(email, password));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form
        className="login-card"
        onSubmit={(event) => {
          event.preventDefault();
          submit(login);
        }}
      >
        <h1>勞動法規問答</h1>
        <p className="muted">依據 26 部勞動法規回答，並附上條號出處</p>

        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <input
          type="password"
          placeholder="密碼（至少 8 碼）"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          minLength={8}
          required
        />

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={busy}>登入</button>
        <button type="button" className="secondary" disabled={busy} onClick={() => submit(register)}>
          註冊新帳號
        </button>
      </form>
    </div>
  );
}
