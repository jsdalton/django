from django.http import HttpResponse
from django.template import RequestContext
from django.shortcuts import get_object_or_404, render_to_response
from models import Person

def get_person(request, pk):
    person = get_object_or_404(Person, pk=pk)
    return HttpResponse(person.name)

def simple_view(request):
    return render_to_response('test_utils/simple_view.html', {
        "foo": "bar"
    }, context_instance=RequestContext(request))
