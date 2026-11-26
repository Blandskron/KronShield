import { zodResolver } from "@hookform/resolvers/zod";
import { useId } from "react";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ApiError } from "../api";
import { Button, Card } from "../ui";

export type Field = {
  name: string; label: string; rule: z.ZodString; type?: string;
  autoComplete?: string;
  options?: { value: string; label: string }[];
};

export const required = z.string().trim().min(1, "Este campo es obligatorio.");
export const uuid = z.string().uuid("Introduce un UUID válido.");
export const slug = z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Usa minúsculas, números y guiones.");

const messages: Record<string, string> = {
  permission_denied: "Tu rol no permite esta operación.",
  authorization_expired: "La vigencia debe terminar en el futuro.",
  approval_requires_distinct_actor: "La decisión requiere una persona distinta de quien solicitó la autorización.",
  invalid_scope_rule: "La regla de alcance no es válida.",
  invalid_target: "La dirección del activo no es válida.",
  invalid_credentials: "Usuario o contraseña incorrectos.",
  bootstrap_already_redeemed: "El código inicial ya se utilizó. Inicia sesión con la cuenta creada.",
  invalid_bootstrap_code: "El código inicial no es válido.",
  resource_conflict: "Hay un registro previo o una referencia incompatible.",
};

export function failure(error: Error): string {
  if (error instanceof ApiError) return messages[error.code] ?? "La API rechazó la solicitud (" + error.status + ").";
  return error.message;
}

export function Form({ title, fields, action, label, completed }: {
  title: string; fields: Field[]; action: (values: Record<string, string>) => Promise<unknown>;
  label: string; completed?: (result: unknown) => void;
}) {
  const prefix = useId();
  const schema = z.object(Object.fromEntries(fields.map((field) => [field.name, field.rule])));
  const { register, handleSubmit, formState, reset } = useForm<Record<string, string>>({ resolver: zodResolver(schema) });
  const request = useMutation({
    mutationFn: action,
    onSuccess: (data) => { reset(); completed?.(data); },
  });
  return <Card className="form-card"><h2>{title}</h2>
    <form onSubmit={handleSubmit((data) => request.mutate(data))}>
      <div className="form-fields">{fields.map((field) => {
        const id = prefix + "-" + field.name;
        const error = formState.errors[field.name];
        const attributes = { id, "aria-invalid": Boolean(error), "aria-describedby": error ? id + "-error" : undefined };
        return <div key={field.name} className="input-field">
          <label htmlFor={id}>{field.label}</label>
          {field.options
            ? <select {...attributes} {...register(field.name)} defaultValue="">
                <option value="" disabled>Seleccionar</option>
                {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            : <input {...attributes} type={field.type ?? "text"} autoComplete={field.autoComplete} {...register(field.name)} />}
          {error && <small id={id + "-error"} role="alert">{error.message}</small>}
        </div>;
      })}</div>
      <Button variant="primary" type="submit" disabled={request.isPending}>{request.isPending ? "Guardando…" : label}</Button>
      {request.error && <p role="alert">{failure(request.error)}</p>}
      {request.isSuccess && <p role="status">Guardado.</p>}
    </form></Card>;
}
