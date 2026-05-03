from django.db import models


# ─────────────────────────────────────────
# LOOKUP TABLES (populated via get-or-create)
# ─────────────────────────────────────────

class StoreBrand(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'store_brands'

    def __str__(self):
        return self.name


class StoreType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'store_types'

    def __str__(self):
        return self.name


class City(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'cities'

    def __str__(self):
        return self.name


class State(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'states'

    def __str__(self):
        return self.name


class Country(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'countries'

    def __str__(self):
        return self.name


class Region(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'regions'

    def __str__(self):
        return self.name


# ─────────────────────────────────────────
# STORES
# ─────────────────────────────────────────

class Store(models.Model):
    store_id = models.CharField(max_length=255, unique=True)           # Natural key from CSV
    store_external_id = models.CharField(max_length=255, default='')
    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)

    # FK to lookup tables — SET NULL if the lookup is deleted
    store_brand = models.ForeignKey(StoreBrand, null=True, blank=True, on_delete=models.SET_NULL)
    store_type = models.ForeignKey(StoreType, null=True, blank=True, on_delete=models.SET_NULL)
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.SET_NULL)
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL)
    country = models.ForeignKey(Country, null=True, blank=True, on_delete=models.SET_NULL)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL)

    latitude = models.FloatField(default=0.0)
    longitude = models.FloatField(default=0.0)
    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stores'

    def __str__(self):
        return f"{self.store_id} — {self.name}"


# ─────────────────────────────────────────
# USERS
# ─────────────────────────────────────────

class User(models.Model):

    USER_TYPE_CHOICES = (
        (1, 'Type 1'),
        (2, 'Type 2'),
        (3, 'Type 3'),
        (7, 'Type 7'),
    )

    username = models.CharField(max_length=150, unique=True)           # Natural key from CSV
    first_name = models.CharField(max_length=150, default='')
    last_name = models.CharField(max_length=150, default='')
    email = models.EmailField(max_length=254)                          # Django validates email format
    user_type = models.IntegerField(choices=USER_TYPE_CHOICES, default=1)
    phone_number = models.CharField(max_length=32, default='')

    # Self-referential FK — a user can have a supervisor who is also a user
    supervisor = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='subordinates'
    )

    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.username


# ─────────────────────────────────────────
# STORE-USER MAPPING (PJP)
# ─────────────────────────────────────────

class PermanentJourneyPlan(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'permanent_journey_plans'
        unique_together = ('user', 'store')         # One user can't be mapped to same store twice

    def __str__(self):
        return f"{self.user.username} → {self.store.store_id}"