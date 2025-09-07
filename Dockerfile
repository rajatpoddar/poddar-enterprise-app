# File: Dockerfile

# --- Build Stage ---
    FROM python:3.9 as builder
    WORKDIR /app
    RUN apt-get update && apt-get install -y build-essential
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    
    # --- Final Stage ---
    FROM python:3.9-slim
    WORKDIR /app
    
    RUN useradd --create-home appuser
    
    COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
    COPY --from=builder /usr/local/bin /usr/local/bin
    
    # Copy the application code AND the new startup script
    COPY . .
    COPY startup.sh .
    
    # Make the startup script executable and set ownership
    RUN chmod +x startup.sh
    RUN chown -R appuser:appuser /app
    
    USER appuser
    
    EXPOSE 5000
    
    # *** THE FIX: Use the startup script as the command ***
    CMD ["./startup.sh"]
    
    