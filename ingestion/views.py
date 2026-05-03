from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ingestion.models import Store, User
from ingestion.services.store_ingestor import ingest_stores
from ingestion.services.user_ingestor import ingest_users
from ingestion.services.pjp_ingestor import ingest_pjp



from ingestion.models import Store, User, PermanentJourneyPlan



class StatusView(APIView):
    """
    GET /api/status/
    Returns count of all ingested data in the database.
    """
    def get(self, request):
        return Response({
            'stores':       Store.objects.count(),
            'users':        User.objects.count(),
            'pjp_mappings': PermanentJourneyPlan.objects.count(),
        }, status=status.HTTP_200_OK)

# ─────────────────────────────────────────
# STORE UPLOAD VIEW
# ─────────────────────────────────────────

class StoreUploadView(APIView):
    """
    POST /api/upload/stores/
    Accepts a CSV file and ingests store data.
    """

    def post(self, request):

        # --- Check if file was provided ---
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file provided. Please upload a CSV file with key "file"'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES['file']

        # --- Check if it's a CSV file ---
        if not file.name.endswith('.csv'):
            return Response(
                {'error': 'Invalid file type. Only CSV files are accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Run the ingestion ---
        try:
            result = ingest_stores(file)
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'Something went wrong: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ─────────────────────────────────────────
# USER UPLOAD VIEW
# ─────────────────────────────────────────

class UserUploadView(APIView):
    """
    POST /api/upload/users/
    Accepts a CSV file and ingests user data.
    """

    def post(self, request):

        # --- Check if file was provided ---
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file provided. Please upload a CSV file with key "file"'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES['file']

        # --- Check if it's a CSV file ---
        if not file.name.endswith('.csv'):
            return Response(
                {'error': 'Invalid file type. Only CSV files are accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Run the ingestion ---
        try:
            result = ingest_users(file)
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'Something went wrong: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ─────────────────────────────────────────
# PJP UPLOAD VIEW
# ─────────────────────────────────────────

class PJPUploadView(APIView):
    """
    POST /api/upload/pjp/
    Accepts a CSV file and ingests store-user mapping data.
    Note: Stores and Users must be uploaded before PJP.
    """

    def post(self, request):

        # --- Enforce upload order ---
        if not Store.objects.exists():
            return Response(
                {
                    'error': 'No stores found in the database.',
                    'hint': 'Please upload stores_master.csv first before uploading PJP mapping.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not User.objects.exists():
            return Response(
                {
                    'error': 'No users found in the database.',
                    'hint': 'Please upload users_master.csv first before uploading PJP mapping.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Check if file was provided ---
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file provided. Please upload a CSV file with key "file"'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES['file']

        # --- Check if it's a CSV file ---
        if not file.name.endswith('.csv'):
            return Response(
                {'error': 'Invalid file type. Only CSV files are accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Run the ingestion ---
        try:
            result = ingest_pjp(file)
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'Something went wrong: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )