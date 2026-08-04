(() => {
  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input, init) => {
    const url = typeof input === "string"
      ? input
      : input instanceof Request
        ? input.url
        : String(input);

    const response = await nativeFetch(input, init);
    const isAnalyzerApi = url.includes("/api/interval/") || url.includes("/api/research/");
    const contentType = response.headers.get("content-type") || "";

    if (isAnalyzerApi && response.status === 404 && contentType.includes("text/html")) {
      return new Response(
        [
          "The live analyzer API is not running.",
          "",
          "Do not start this page with: python -m http.server",
          "",
          "Windows: double-click start-windows.bat",
          "PowerShell: .\\start.ps1",
          "Manual: python -m uvicorn app.interval_main:app --app-dir backend --reload --port 8000",
          "",
          "Then open http://localhost:8000/",
        ].join("\n"),
        {
          status: 503,
          statusText: "Live analyzer API not running",
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        },
      );
    }

    return response;
  };
})();
