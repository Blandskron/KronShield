import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { z } from "zod";
import { api, type Models } from "../api";
import { Button } from "../ui";
import { Form, required, type Field } from "./forms";

export function SignIn({ brand }: { brand: ReactNode }) {
  const cache = useQueryClient();
  const [bootstrap, setBootstrap] = useState(false);
  const mode = useQuery({ queryKey: ["auth-mode"], queryFn: ({ signal }) => api<Models["AuthMode"]>("/auth/mode", { signal }) });
  const fields: Field[] = [
    { name: "username", label: "Usuario", rule: required },
    { name: "password", label: "Contraseña", rule: z.string().min(12).max(128), type: "password" },
  ];
  if (bootstrap) fields.unshift({ name: "code", label: "Código inicial", rule: z.string().min(32), type: "password" });
  function send<T>(path: string, data: Record<string, string>) {
    return api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  }
  return <div className="sign-in">
    <div className="sign-in-identity">{brand}</div>
    <main id="main" className="login-card">
      <div className="login-icon"><ShieldCheck size={26} aria-hidden /></div>
      <h1>Accede a tu espacio</h1>
      {mode.data?.mode === "pilot" ? <>
        <Form key={String(bootstrap)} title={bootstrap ? "Administrador inicial" : "Acceso al piloto"}
          fields={fields} label={bootstrap ? "Crear primer administrador" : "Iniciar sesión"} action={async (values) => {
            const { username, password } = values;
            if (bootstrap) await send("/bootstrap/redeem", values);
            await send("/auth/local/login", { username, password });
          }} completed={() => { void cache.invalidateQueries({ queryKey: ["session"] }); }} />
        <Button onClick={() => setBootstrap(!bootstrap)}>{bootstrap ? "Volver a iniciar sesión" : "Primer acceso"}</Button>
      </> : <><p>Inicia sesión para consultar los proyectos de tu organización.</p>
        <Button asChild variant="primary"><a href="/api/v1/auth/login">Iniciar sesión</a></Button></>}
    </main>
  </div>;
}
