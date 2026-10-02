"""Expose parsed multipart field names only in the isolated upload E2E app."""


class UploadContractObservationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method == "POST" and request.path in {
            "/api/agent/blog/images/",
            "/api/agent/documents/",
        }:
            fields = set(request.POST.keys()) | set(request.FILES.keys())
            response["X-E2E-Multipart-Fields"] = ",".join(sorted(fields))
        return response
