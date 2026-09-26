import { useState } from "react";
import Chat from "./Chat";
import Login from "./Login";

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("token"));

  function handleAuth(newToken) {
    localStorage.setItem("token", newToken);
    setToken(newToken);
  }

  function handleLogout() {
    localStorage.removeItem("token");
    setToken(null);
  }

  return token ? <Chat token={token} onLogout={handleLogout} /> : <Login onAuth={handleAuth} />;
}
