/**
 * clima.js - Widget de Clima para Calama, Chile
 * Consulta Open-Meteo y endpoint local /api/clima/
 * Soporta Sol radiante, Nublado, Noche (Luna), Atardecer / Tarde
 */

(function () {
  'use strict';

  function aplicarClimaEnDOM(clima) {
    if (!clima) return;

    const iconos = document.querySelectorAll('.clima-icono');
    const temps = document.querySelectorAll('.clima-temp');
    const pills = document.querySelectorAll('.clima-pill');
    const descs = document.querySelectorAll('.clima-desc');

    const icono = clima.icono || '☀️';
    const tempTxt = clima.temperatura_texto || (clima.temperatura !== undefined ? Math.round(clima.temperatura) + '°C' : '--°C');
    const descTxt = clima.descripcion || 'Calama';

    iconos.forEach(el => { el.textContent = icono; });
    temps.forEach(el => { el.textContent = tempTxt; });
    descs.forEach(el => { el.textContent = descTxt; });
    pills.forEach(el => {
      el.title = `Clima actual en Calama: ${descTxt} (${tempTxt})`;
    });
  }

  // Exportar al objeto global para que la TV lo invoque directamente
  window.actualizarClimaUI = aplicarClimaEnDOM;

  async function consultarClima() {
    // 1. Intentar endpoint local Django
    try {
      const resp = await fetch('/api/clima/?_t=' + Date.now());
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.status === 'ok') {
          aplicarClimaEnDOM(data);
          return;
        }
      }
    } catch (e) {
      // Si falla local, intentar fallback directo a Open-Meteo
    }

    // 2. Fallback directo a Open-Meteo desde el navegador (CORS habilitado por Open-Meteo)
    try {
      const urlOM = 'https://api.open-meteo.com/v1/forecast?latitude=-22.4544&longitude=-68.9294&current=temperature_2m,is_day,weather_code&timezone=America%2FSantiago';
      const respOM = await fetch(urlOM);
      if (respOM.ok) {
        const payload = await respOM.json();
        const curr = payload.current || {};
        const temp = curr.temperature_2m !== undefined ? Math.round(curr.temperature_2m) : 22;
        const isDay = curr.is_day !== undefined ? curr.is_day : 1;
        const code = curr.weather_code || 0;

        const now = new Date();
        // Hora en Chile (aproximada por Date o UTC-3)
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
          ciudad: 'Calama'
        };
        aplicarClimaEnDOM(dataClima);
      }
    } catch (err) {
      console.warn('No fue posible consultar el clima:', err);
    }
  }

  // Ejecutar al cargar la página
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', consultarClima);
  } else {
    consultarClima();
  }

  // Refrescar cada 15 minutos automáticamente
  setInterval(consultarClima, 15 * 60 * 1000);
})();
