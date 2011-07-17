from django.db import models


class Person(models.Model):
    name = models.CharField(max_length=100)

class Pet(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(Person)

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ('name',)
