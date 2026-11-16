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
        <h1>US Labor Law Assistant</h1>
        <p className="muted">Answers from U.S. federal labor regulations, with a citation for every claim.</p>

        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Password (at least 8 characters)"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          minLength={8}
          required
        />

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={busy}>Log in</button>
        <button type="button" className="secondary" disabled={busy} onClick={() => submit(register)}>
          Create account
        </button>
      </form>
    </div>
  );
}
