import { startServices } from "./start-services.mjs";

export default async function globalSetup() {
  const stop = await startServices();
  const frontendPort = process.env.E2E_FRONTEND_PORT || "5173";
  const url = `http://127.0.0.1:${frontendPort}/login`;
  try {
    for (let attempt = 0; attempt < 150; attempt += 1) {
      try {
        const response = await fetch(url);
        if (response.status < 500) return stop;
      } catch {
        // Vite is still starting; keep waiting within the bounded window.
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    throw new Error("Vite upload E2E server did not become ready within 30 seconds.");
  } catch (error) {
    await stop();
    throw error;
  }
}
