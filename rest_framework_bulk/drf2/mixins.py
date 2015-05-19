from __future__ import unicode_literals, print_function
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.mixins import CreateModelMixin
from rest_framework.response import Response


__all__ = [
    'BulkCreateModelMixin',
    'BulkDestroyModelMixin',
    'BulkUpdateModelMixin',
]


class BulkCreateModelMixin(CreateModelMixin):
    """
    Either create a single or many model instances in bulk by using the
    Serializers ``many=True`` ability from Django REST >= 2.2.5.

    .. note::
        This mixin uses the same method to create model instances
        as ``CreateModelMixin`` because both non-bulk and bulk
        requests will use ``POST`` request method.

    Our addons:
    * View setting 'post_force_bulk' - forces POST to bulk mode.
    * View setting 'post_allow_update' - allows bulk POST to update existing objects
                                         (when identity exists, usually 'id' field).
    - pre_bulk_save(self, objs): pre save all objects.
    - post_bulk_save(self, objs): post save all objects.
    NOTE: pre_save, post_save gets each single object from the bulk.
    """

    post_force_bulk = False
    post_allow_update = False

    def pre_bulk_save(self, objs):
        pass
    def post_bulk_save(self, objs):
        pass

    def create(self, request, *args, **kwargs):
        post_force_bulk = kwargs.pop('post_force_bulk', getattr(self, 'post_force_bulk', False))
        post_allow_update = kwargs.pop('post_allow_update', getattr(self, 'post_allow_update', False))

        bulk = isinstance(request.DATA, list)

        if not bulk and not post_force_bulk:
            return super(BulkCreateModelMixin, self).create(request, *args, **kwargs)

        else:
            serializer = self.get_serializer(data=request.DATA, many=True)

            # if allow bulk POST to also update existing objects:
            if post_allow_update:
                # filter serializer object instance list to only objects that are requested to be updated:
                ids_list = []
                for item in request.DATA:
                    item_identity = serializer.get_identity(item)
                    if item_identity:
                        ids_list.append(item_identity)
                pk_field = self.model._meta.pk
                instance_qs = self.filter_queryset(self.get_queryset())  # restrict the update to filtered queryset
                instance_qs = instance_qs.filter(**{pk_field.name+'__in': ids_list})  # restrict the update to existing items in request data
                # use this serializer for bulk POST with update, so allow_add_remove will not delete any item:
                serializer = self.get_serializer(instance_qs,
                                                 data=request.DATA,
                                                 many=True,
                                                 allow_add_remove=True,
                                                 partial=False)

            if serializer.is_valid():
                for obj in serializer.object:
                    self.pre_save(obj)
                self.pre_bulk_save(serializer.object)
                self.object = serializer.save(force_insert=not post_allow_update)
                self.post_bulk_save(serializer.object)
                for obj in self.object:
                    self.post_save(obj, created=True)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BulkUpdateModelMixin(object):
    """
    Update model instances in bulk by using the Serializers
    ``many=True`` ability from Django REST >= 2.2.5.

    Our addons:
    - pre_bulk_save(self, objs): pre save all objects.
    - post_bulk_save(self, objs): post save all objects.
    NOTE: pre_save, post_save gets each single object from the bulk.
    """

    def get_object(self, queryset=None):
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        if any((lookup_url_kwarg in self.kwargs,
                self.pk_url_kwarg in self.kwargs,
                self.slug_url_kwarg in self.kwargs)):
            return super(BulkUpdateModelMixin, self).get_object(queryset)

        # If the lookup_url_kwarg (or other deprecated variations)
        # are not present, get_object() is most likely called
        # as part of metadata() which by default simply checks
        # for object permissions and raises permission denied if necessary.
        # Here we don't need to check for general permissions
        # and can simply return None since general permissions
        # are checked in initial() which always gets executed
        # before any of the API actions (e.g. create, update, etc)
        return

    def pre_bulk_update(self, objs):
        pass
    def post_bulk_update(self, objs):
        pass

    def bulk_update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)

        # restrict the update to the filtered queryset
        serializer = self.get_serializer(self.filter_queryset(self.get_queryset()),
                                         data=request.DATA,
                                         many=True,
                                         partial=partial)

        if serializer.is_valid():
            try:
                for obj in serializer.object:
                    self.pre_save(obj)
            except ValidationError as err:
                # full_clean on model instances may be called in pre_save
                # so we have to handle eventual errors.
                return Response(err.message_dict, status=status.HTTP_400_BAD_REQUEST)
            self.pre_bulk_update(serializer.object)
            self.object = serializer.save(force_update=True)
            self.post_bulk_update(serializer.object)
            for obj in self.object:
                self.post_save(obj, created=False)
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def partial_bulk_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.bulk_update(request, *args, **kwargs)


class BulkDestroyModelMixin(object):
    """
    Destroy model instances from a list.
    Must specify ?idList=id1,id2,... in the query-params, otherwise the
    bulk will fail (This asserts that no one deletes the whole list without
    explicitly specify which items to delete).

    Our changes and addons:
    - We force to delete the object through the serializer with delete_object method.
    - pre_bulk_delete(self, objs): pre delete all objects.
    - post_bulk_delete(self, objs): post delete all objects.
    NOTE: pre_delete, post_delete gets each single object from the bulk.
    """

    def pre_bulk_delete(self, objs):
        pass
    def post_bulk_delete(self, objs):
        pass

    def destroy(self, request, *args, **kwargs):
        #get filtered queryset:
        qs = self.filter_queryset(self.get_queryset())

        #do not allow delete all the list without specifying the ids explicitly:
        del_list_value = request.QUERY_PARAMS.get('idList', None)
        if del_list_value is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        del_list_strs = filter(None, [x.strip() for x in unicode(del_list_value).split(',')])
        del_list = [int(x) for x in del_list_strs if x.isnumeric()]
        pk_name = self.model._meta.pk.name
        filtered = qs.filter(**{pk_name+'__in': del_list})

        #create a serializer from the destroy filtered list (in order to use serializer delete_object method):
        serializer = self.get_serializer(filtered,
                                         data=[{pk_name: getattr(x, pk_name, None)} for x in filtered],
                                         many=True,
                                         partial=True)

        #delete the objects in serializer:
        if serializer.is_valid():  #Note: serializer should be valid always
            for obj in serializer.object:
                self.pre_delete(obj)
            self.pre_bulk_delete(serializer.object)
            for obj in serializer.object:
                serializer.delete_object(obj)
            self.post_bulk_delete(serializer.object)
            for obj in serializer.object:
                self.post_delete(obj)
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
