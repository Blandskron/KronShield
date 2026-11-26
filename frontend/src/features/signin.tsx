import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { FileCheck2, Layers3, ShieldCheck } from "lucide-react";
import { api, ApiError, type Models } from "../api";
import { Button } from "../ui";
import { Brand, ThemeControl } from "../brand";
import shieldField from "../assets/kronshield-field.svg";
export function SignIn({ checkingSession }: { checkingSession: boolean }) {
  const cache = useQueryClient();
  const [bootstrap, setBootstrap] = useState(false);
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState("");
  const mode = useQuery({ queryKey: ["auth-mode"], queryFn: ({ signal }) => api<Models["AuthMode"]>("/auth/mode", { signal }) });
  const pilot = mode.data?.mode === "pilot";
  const checking = checkingSession || mode.isPending;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") ?? "").trim();
    const password = String(form.get("password") ?? "");
    if (!username) { setProblem("Introduce tu usuario."); return; }
    const send = (path: string, data: Record<string, string>) =>
      api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    setPending(true);
    setProblem("");
    try {
      if (bootstrap) await send("/bootstrap/redeem", { username, password, code: String(form.get("code") ?? "") });
      await send("/auth/local/login", { username, password });
      await cache.invalidateQueries({ queryKey: ["session"] });
    } catch (error) {
      const code = error instanceof ApiError ? error.code : "";
      const messages: Record<string, string> = {
        invalid_credentials: "Usuario o contraseña incorrectos.",
        bootstrap_already_redeemed: "El código inicial ya se utilizó. Inicia sesión con la cuenta creada.",
        invalid_bootstrap_code: "El código inicial no es válido.",
      };
      setProblem(messages[code] ?? "No se pudo completar el acceso. Vuelve a intentarlo.");
    } finally {
      setPending(false);
    }
  }
  return <div className="sign-in">
    <header className="landing-header"><Brand /><ThemeControl /></header>
    <main id="main" className="landing-main">
      <section className="sign-in-identity" aria-labelledby="landing-statement">
        <div className="landing-copy">
          <h1 id="landing-statement">Intelligent Security.<br /><span>Responsible by Design.</span></h1>
          <p>Gestiona autorizaciones, revisa el alcance y conserva la evidencia de tus auditorías en un mismo espacio.</p>
          <ul className="landing-capabilities">
            <li><Layers3 size={17} aria-hidden /> Proyectos y activos</li>
            <li><ShieldCheck size={17} aria-hidden /> Simulaciones sin conexión</li>
            <li><FileCheck2 size={17} aria-hidden /> Informes verificables</li>
          </ul>
        </div>
        <img src={shieldField} alt="" width="520" height="332" className="landing-art" />
      </section>
      <section className="login-card" aria-labelledby="sign-in-heading" aria-busy={checking || pending}
        data-full={checking || pilot}>
      <div className="login-icon"><ShieldCheck size={24} aria-hidden /></div>
      <h2 id="sign-in-heading">Accede a tu espacio</h2>
      {checking ? <p role="status">Comprobando el acceso…</p> : pilot ? <>
        <form className="login-form" key={String(bootstrap)} onSubmit={submit}>
          <h3>{bootstrap ? "Administrador inicial" : "Acceso al piloto"}</h3>
          {bootstrap && <label className="input-field">Código inicial
            <input name="code" type="password" minLength={32} autoComplete="off" required />
          </label>}
          <label className="input-field">Usuario
            <input name="username" autoComplete="username" required />
          </label>
          <label className="input-field">Contraseña
            <input name="password" type="password" minLength={12} maxLength={128}
              autoComplete={bootstrap ? "new-password" : "current-password"} required />
          </label>
          <Button type="submit" variant="primary" disabled={pending}>
            {pending ? "Comprobando…" : bootstrap ? "Crear primer administrador" : "Iniciar sesión"}
          </Button>
          {problem && <p role="alert">{problem}</p>}
        </form>
        <Button disabled={pending} onClick={() => { setProblem(""); setBootstrap(!bootstrap); }}>
          {bootstrap ? "Volver a iniciar sesión" : "Primer acceso"}
        </Button>
      </> : <><p>Inicia sesión para consultar los proyectos de tu organización.</p>
        <Button asChild variant="primary"><a href="/api/v1/auth/login">Iniciar sesión</a></Button></>}
      </section>
    </main>
    <footer className="landing-footer"><span>Open Source · By BLANDSKRON</span>
      <a href="https://github.com/Blandskron/KronShield">Repositorio</a></footer>
  </div>;
}
