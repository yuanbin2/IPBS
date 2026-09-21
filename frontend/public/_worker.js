export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // If the request is for a static asset, serve it directly
    if (url.pathname.startsWith('/assets/')) {
      return env.ASSETS.fetch(request);
    }

    // For all other routes, serve index.html (SPA routing)
    const indexRequest = new Request(`${url.origin}/index.html`, request);
    return env.ASSETS.fetch(indexRequest);
  }
};
