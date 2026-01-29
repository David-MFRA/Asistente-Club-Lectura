# 💾 Persistencia de Datos con PostgreSQL

## ⚠️ Problema en el Plan Gratuito de Render

En Render Free, el archivo `club_data.json` se **borra cada vez que re-despliegas** porque el sistema de archivos es efímero.

### Síntomas:
- Al actualizar el bot, pierdes todo el historial
- Las sugerencias de libros desaparecen
- Las estadísticas de usuarios se resetean

---

## 💡 Soluciones

### Opción 1: Aceptar la limitación (Más simple)

**Para grupos pequeños y casuales:**

- Re-despliega solo cuando sea absolutamente necesario
- Antes de re-desplegar, pide a alguien que copie el historial manualmente
- Usa el bot sabiendo que los datos son temporales

**Ventajas:**
- No requiere cambios en el código
- Mantiene la simplicidad

**Desventajas:**
- Pierdes datos con cada actualización

---

### Opción 2: PostgreSQL en Render (Recomendado)

**Para grupos serios que quieren mantener todo el historial:**

Render ofrece PostgreSQL gratuito por 90 días (después puedes crear uno nuevo).

### Paso 1: Crear base de datos en Render

1. Dashboard de Render > **New +**
2. Selecciona **PostgreSQL**
3. Nombre: `club-lectura-db`
4. Database: `club_lectura`
5. User: (se genera automáticamente)
6. Region: (la misma que tu bot)
7. Instance Type: **Free**
8. Clic en **Create Database**

### Paso 2: Obtener credenciales

1. Espera que se cree (1-2 minutos)
2. Copia la **Internal Database URL**
   - Se ve así: `postgresql://user:pass@hostname/dbname`
3. Ve a tu servicio del bot
4. Settings > Environment
5. Add Environment Variable:
   - Key: `DATABASE_URL`
   - Value: (pega la Internal Database URL)

### Paso 3: Actualizar requirements.txt

Añade esta línea a `requirements.txt`:

```
psycopg2-binary==2.9.9
```

El archivo completo quedaría:
```
python-telegram-bot==21.0.1
python-dotenv==1.0.0
psycopg2-binary==2.9.9
```

### Paso 4: Código para PostgreSQL

Necesitarías crear un nuevo archivo `database.py`:

```python
import psycopg2
import json
import os
from psycopg2.extras import Json

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        self.create_tables()
    
    def create_tables(self):
        """Crea las tablas necesarias"""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS club_data (
                id INTEGER PRIMARY KEY DEFAULT 1,
                data JSONB NOT NULL
            )
        ''')
        self.conn.commit()
        cursor.close()
    
    def cargar_datos(self):
        """Carga los datos desde PostgreSQL"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT data FROM club_data WHERE id = 1')
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            return result[0]
        else:
            # Datos por defecto
            datos_iniciales = {
                'libros_sugeridos': [],
                'libro_actual': None,
                'libros_leidos': [],
                'proxima_reunion': None,
                'miembros': {},
                'discusiones': [],
                'votaciones_activas': {},
                'citas': []
            }
            self.guardar_datos(datos_iniciales)
            return datos_iniciales
    
    def guardar_datos(self, data):
        """Guarda los datos en PostgreSQL"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO club_data (id, data) 
            VALUES (1, %s)
            ON CONFLICT (id) 
            DO UPDATE SET data = %s
        ''', (Json(data), Json(data)))
        self.conn.commit()
        cursor.close()
```

Y modificar `club_lectura_bot.py` para usar la base de datos:

```python
# Al inicio del archivo
from database import Database

# En la clase ClubLecturaBot
class ClubLecturaBot:
    def __init__(self):
        # Detectar si hay DATABASE_URL
        if os.getenv('DATABASE_URL'):
            print("📊 Usando PostgreSQL para persistencia")
            self.db = Database()
            self.data = self.db.cargar_datos()
        else:
            print("📁 Usando archivo JSON (datos no persistentes)")
            self.data = self.cargar_datos()
    
    def guardar_datos(self):
        """Guarda los datos"""
        if hasattr(self, 'db'):
            self.db.guardar_datos(self.data)
        else:
            # Guardar en JSON como antes
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
```

**⚠️ NOTA:** Esta es una implementación simplificada. Para producción, deberías manejar mejor los errores y conexiones.

---

### Opción 3: Replit (Alternativa a Render)

**Replit mantiene los archivos automáticamente:**

Ventajas de Replit:
- ✅ Los archivos persisten automáticamente
- ✅ No se pierden datos entre reinicios
- ✅ Interfaz más simple
- ✅ Editor de código integrado

Desventajas:
- ⚠️ El bot se "duerme" si no hay actividad (plan free)
- ⚠️ Necesitas mantener un "keep alive" para 24/7

**Cómo usar Replit:**

1. Ve a https://replit.com
2. Crea cuenta (gratis)
3. New Repl > Import from GitHub
4. Pega tu repositorio
5. En "Secrets" (candado), añade:
   - Key: `TELEGRAM_BOT_TOKEN`
   - Value: tu token
6. Clic en "Run"
7. Para mantenerlo 24/7: usa UptimeRobot (https://uptimerobot.com)

---

### Opción 4: Railway (Otra alternativa)

**Railway es similar a Render pero con mejor persistencia:**

1. https://railway.app
2. Sign up with GitHub
3. New Project > Deploy from GitHub
4. Selecciona tu repo
5. Add variables > `TELEGRAM_BOT_TOKEN`
6. Deploy

Railway ofrece $5 de crédito gratis al mes, suficiente para un bot pequeño.

---

## 📊 Comparativa de Opciones

| Opción | Persistencia | Complejidad | Costo | Uptime |
|--------|--------------|-------------|-------|--------|
| Render + JSON | ❌ No | ⭐ Fácil | Gratis | 24/7* |
| Render + PostgreSQL | ✅ Sí | ⭐⭐⭐ Media | Gratis 90d | 24/7* |
| Replit | ✅ Sí | ⭐⭐ Fácil | Gratis | Parcial** |
| Railway | ✅ Sí | ⭐⭐ Fácil | $5/mes gratis | 24/7 |

\* Se duerme tras 15 min de inactividad pero despierta al recibir mensaje
\** Requiere "keep alive" para 24/7

---

## 🎯 Recomendación

### Para empezar (pruebas):
**Render + JSON** (lo que ya tienes)
- Es gratis
- Funciona bien
- Acepta perder datos al actualizar

### Para uso serio:
**Render + PostgreSQL**
- Gratis por 90 días
- Luego migrar a Railway ($5/mes)
- O crear nueva DB en Render cada 90 días

### Para simplicidad máxima:
**Replit**
- Archivos persisten automáticamente
- Muy fácil de usar
- Ideal para no programadores

---

## 🔄 Migración de Datos

Si quieres migrar tus datos de JSON a PostgreSQL:

1. Antes de cambiar a PostgreSQL, descarga tu `club_data.json`
2. Guárdalo en tu computadora
3. Después de configurar PostgreSQL, puedes "importar" los datos manualmente

---

## ❓ FAQ

**P: ¿Cuánto cuesta PostgreSQL en Render después de 90 días?**
R: $7/mes para el plan Basic, pero puedes crear una nueva DB gratis cada 90 días.

**P: ¿Pierdo datos si el bot se "duerme"?**
R: No, solo se pausan los procesos. Los datos en PostgreSQL persisten.

**P: ¿Puedo usar SQLite en Render?**
R: No es recomendable porque SQLite guarda en archivos que se borran al re-desplegar.

**P: ¿Qué pasa si mi PostgreSQL gratis expira?**
R: Puedes:
1. Exportar datos
2. Crear nueva DB gratis
3. Importar datos
4. Actualizar la DATABASE_URL

---

## 📝 Conclusión

Para tu club de lectura:

1. **Empieza con Render + JSON** (lo que ya tienes configurado)
2. Si el club crece y quieres mantener historial → Migra a PostgreSQL
3. Si quieres máxima simplicidad → Usa Replit

**Lo importante es empezar y disfrutar de las lecturas.** La persistencia perfecta puede venir después. 📚✨
