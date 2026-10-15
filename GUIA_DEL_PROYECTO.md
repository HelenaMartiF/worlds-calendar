# Mundial de LoL en mi Google Calendar

## Qué es

Un pequeño programa que apunta **todos los partidos del Mundial de League of Legends (Worlds)** en un calendario de Google dedicado, y los mantiene al día solo:

- Cuando un hueco pasa de "TBD vs TBD" a "T1 vs GEN", el evento cambia de título.
- Si Riot mueve un partido de hora, el evento se mueve.
- Si borras un evento sin querer, vuelve a aparecer en la siguiente sincronización.

Funciona como un **asistente que cada media hora mira la web oficial de lolesports y corrige tu agenda** si algo ha cambiado.

## Cómo funciona (las tres piezas)

1. **La fuente: la API de lolesports.com.** Es la misma "ventanilla" de donde la web oficial saca el calendario. No es oficial para el público, pero es abierta y estable desde hace años. Cada partido tiene un número de identificación fijo, incluso cuando aún no se saben los equipos.
2. **El script `sync.py`.** Pide la lista de partidos, la traduce a eventos de calendario y se los manda a Google. A cada evento le pone como "DNI" el número del partido (`lol` + número). Así, si lo ejecutas 100 veces, no duplica nada: busca el evento por su DNI y solo lo toca si ha cambiado.
3. **El reloj: GitHub Actions.** Un ordenador de GitHub ejecuta el script cada 30 minutos de forma gratuita, sin que tu PC tenga que estar encendido.

## Decisiones y por qué

| Decisión | Por qué |
|---|---|
| Calendario **dedicado** (no el principal) | Lo puedes ocultar, colorear o borrar entero de un golpe al acabar el Mundial. |
| **Cuenta de servicio** de Google en lugar de iniciar sesión | Es como darle una llave solo de ese calendario a un "robot". No tiene acceso a tu correo ni a tus otros calendarios. |
| API en lugar de un enlace `.ics` | Google refresca los calendarios suscritos por enlace cada 12–24 h; así los TBD se resuelven en minutos. |
| **Sin resultados** en el título por defecto | Para no comerte spoilers si ves el partido en diferido. Se activa con `SHOW_RESULTS=true`. |
| Eventos marcados como "disponible" | Para que no te bloqueen la agenda como si fueran reuniones. |
| Duración: Bo1 = 1 h, Bo3 = 3 h, Bo5 = 5 h | Estimación; la API no da la hora de fin. |
| Horas guardadas en UTC | Google las muestra en tu zona horaria (y gestiona el cambio de hora del 25 de octubre). |

## Puesta en marcha (una sola vez)

### 1. Crear el calendario
1. En [Google Calendar](https://calendar.google.com) → *Otros calendarios* → **+** → *Crear calendario*. Nombre: `Worlds LoL`.
2. En su configuración, apunta el **ID del calendario** (sección *Integrar el calendario*, algo como `abc123@group.calendar.google.com`).

### 2. Crear el "robot" (cuenta de servicio)
1. Ve a [console.cloud.google.com](https://console.cloud.google.com) con tu cuenta **personal** y crea un proyecto (p. ej. `worlds-calendar`).
2. *APIs y servicios* → *Biblioteca* → busca **Google Calendar API** → *Habilitar*.
3. *IAM y administración* → *Cuentas de servicio* → *Crear cuenta de servicio* (nombre `worlds-sync`, sin roles).
4. Entra en la cuenta → pestaña *Claves* → *Agregar clave* → *JSON*. Se descarga un archivo: **es una contraseña, no lo subas a ningún sitio ni lo pegues en un chat.**
5. Copia el email de la cuenta (`worlds-sync@...iam.gserviceaccount.com`).

### 3. Darle la llave del calendario
En la configuración del calendario `Worlds LoL` → *Compartir con personas concretas* → añade el email del robot con permiso **"Hacer cambios en eventos"**.

### 4. Guardar los secretos en GitHub
En el repositorio → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*:
- `GOOGLE_CALENDAR_ID` → el ID del paso 1.
- `GOOGLE_SERVICE_ACCOUNT_JSON` → el contenido entero del archivo JSON.

(Opcional, pestaña *Variables*: `SHOW_RESULTS` = `true` si quieres ver los marcadores.)

Después borra el archivo JSON de Descargas.

### 5. Primera ejecución
Pestaña *Actions* → *Sincronitza Worlds* → **Run workflow**. En un minuto tendrás los partidos en el calendario.

## Probarlo en tu ordenador

```bash
pip install -r requirements.txt
python sync.py --dry-run
```

`--dry-run` ("ensayo") solo muestra la lista de partidos, sin tocar Google.

## Glosario

- **API**: una "ventanilla" por la que un programa pide datos a otro servicio.
- **TBD** (*to be determined*): equipo aún por decidir.
- **Bo1 / Bo3 / Bo5**: al mejor de 1, 3 o 5 partidas.
- **Play-ins / Swiss / Cuartos…**: fases del torneo. El sistema suizo empareja a equipos con el mismo balance de victorias y derrotas.
- **Cuenta de servicio**: un usuario "robot" de Google, con permisos solo sobre lo que tú le compartes.
- **GitHub Actions**: ordenadores de GitHub que ejecutan tareas automáticas.
- **Cron**: forma de decir "cada X tiempo" (aquí, `*/30 * * * *` = cada 30 minutos).
- **Secret**: valor guardado cifrado en GitHub que el programa puede leer pero nadie puede ver.

## Registro de cambios

- **2026-10-15** — Versión inicial: script, sincronización cada 30 min, guía de configuración.
