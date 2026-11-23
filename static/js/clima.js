/**
 * clima.js - Widget de Clima para Calama, Chile
 * Consulta Open-Meteo directamente desde el navegador para obtener la temperatura en tiempo real exacta.
 * Usa almacenamiento local (localStorage) para persistencia instantánea y evitar parpadeos.
 * Incluye timeout de 8s para no congelar la TV si la red falla.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'calama_clima_data_v2';

  function aplicarClimaEnDOM(clima) {
    if (!clima) return;

    const iconos = document.querySelectorAll('.clima-icono');
    const temps = document.querySelectorAll('.clima-temp');
    const pills = document.querySelectorAll('.clima-pill');
    const descs = document.querySelectorAll('.clima-desc');

    const icono = clima.icono || '☀️';
    const tempTxt = clima.temperatura_texto || (clima.temperatura !== undefined ? Math.round(clima.temperatura) + '°C' : '25°C');
    const descTxt = clima.descripcion || 'Calama';

    iconos.forEach(el => { el.textContent = icono; });
    temps.forEach(el => { el.textContent = tempTxt; });
    descs.forEach(el => { el.textContent = descTxt; });
    pills.forEach(el => {
      el.title = `Clima actual en Calama: ${descTxt} (${tempTxt})`;
    });

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(clima));
    } catch (e) {}
  }

  // Exportar al objeto global
  window.actualizarClimaUI = aplicarClimaEnDOM;

  // Restaurar de inmediato el último clima guardado para que no parpadee
  try {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (cached) {
      aplicarClimaEnDOM(JSON.parse(cached));
    }
  } catch (e) {}

  // Fetch con timeout para no bloquear la TV si la red falla
  async function fetchConTimeout(url, opciones, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const resp = await fetch(url, { ...opciones, signal: controller.signal });
      clearTimeout(timer);
      return resp;
    } catch (e) {
      clearTimeout(timer);
      throw e;
    }
  }

  async function consultarClima() {
    // 1. Consulta directa a Open-Meteo desde el navegador (temperatura viva sin proxy)
    // Timeout 8 segundos — si tarda más, usa el caché local y no congela la TV
    try {
      const urlOM = 'https://api.open-meteo.com/v1/forecast?latitude=-22.4544&longitude=-68.9294&current=temperature_2m,is_day,weather_code&timezone=America%2FSantiago';
      const respOM = await fetchConTimeout(urlOM, { cache: 'no-store' }, 8000);
      if (respOM.ok) {
        const payload = await respOM.json();
        const curr = payload.current || {};
        const rawTemp = curr.temperature_2m !== undefined ? curr.temperature_2m : 25;
        // Redondeo estándar (24.5 -> 25°C exactamente igual a las apps del celular)
        const temp = Math.round(rawTemp);
        const isDay = curr.is_day !== undefined ? curr.is_day : 1;
        const code = curr.weather_code || 0;

        const now = new Date();
        const horaChile = new Date(now.toLocaleString('en-US', { timeZone: 'America/Santiago' })).getHours();
        const esTarde = (isDay === 1 && (horaChile >= 18 && horaChile < 21));

        let icono = '☀️';
        let desc = 'Soleado';

        if (isDay === 0) {
          if (code <= 1) { icono = '🌙'; desc = 'Noche despejada'; }
          else if (code === 2) { icono = '☁️'; desc = 'Noche con nubes'; }
          else if (code === 3) { icono = '☁️'; desc = 'Nublado'; }
          else if (code >= 51) { icono = '🌧️'; desc = 'Lluvia'; }
          else { icono = '🌙'; desc = 'Noche'; }
        } else if (esTarde) {
          if (code <= 1) { icono = '🌇'; desc = 'Atardecer despejado'; }
          else if (code === 2) { icono = '⛅'; desc = 'Tarde parcialmente nublada'; }
          else if (code === 3) { icono = '☁️'; desc = 'Tarde nublada'; }
          else { icono = '🌇'; desc = 'Atardecer'; }
        } else {
          if (code === 0) { icono = '☀️'; desc = 'Soleado'; }
          else if (code <= 2) { icono = '🌤️'; desc = 'Parcialmente nublado'; }
          else if (code === 3) { icono = '☁️'; desc = 'Nublado'; }
          else if (code === 45 || code === 48) { icono = '🌫️'; desc = 'Neblina'; }
          else if (code >= 51) { icono = '🌧️'; desc = 'Lluvia'; }
          else { icono = '☀️'; desc = 'Soleado'; }
        }

        const dataClima = {
          temperatura: temp,
          temperatura_texto: `${temp}°C`,
          icono: icono,
          descripcion: desc,
          ciudad: 'Calama',
          fuente: 'open-meteo-direct'
        };
        aplicarClimaEnDOM(dataClima);
        return;
      }
    } catch (e) {
      // Timeout o error de red — continúa con caché local ya aplicado, no hace nada más
      console.warn('[clima] Open-Meteo no disponible, usando caché:', e && e.name);
      return;
    }
  }

  // Lanzar DESPUÉS del DOM, con retraso de 3s para no competir con el arranque de la rotación
  function iniciarClima() {
    setTimeout(consultarClima, 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciarClima);
  } else {
    iniciarClima();
  }

  // Refrescar cada 10 minutos automáticamente
  setInterval(consultarClima, 10 * 60 * 1000);
})();

