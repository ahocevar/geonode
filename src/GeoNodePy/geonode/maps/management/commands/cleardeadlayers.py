from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.signals import pre_delete
from geonode.maps.models import Layer, Map, delete_layer
from urllib2 import URLError
from optparse import make_option
from django.conf import settings

class Command(BaseCommand):
    help = """
    Identifies and removes layers in the Django app which don't correspond to
    layers in the GeoServer catalog.  Such layers were created by an
    error-handling bug in GeoNode 1.0-RC2 and earlier.

    New functionality allows wiping of specific layers by uuids, finding
    geonetwork layers that are 'orphaned', maps that are missing layers
    and dryrun support.
    """
    args = '[uuid...]'
    option_list = BaseCommand.option_list + (
            make_option('--geonetwork', dest="geonetwork", default=False, action="store_true",
                help="Delete geonetwork layers, too"),
            make_option('--maps', dest="maps", default=False, action="store_true",
                help="Delete maps with missing layers, too"),
            make_option('--execute', dest="execute", default=False, action="store_true",
                help="If not provided, only print what would be done")
        )

    @transaction.commit_on_success()
    def handle(self, *args, **opts):
        self.dryrun = not opts['execute']
        if self.dryrun:
            print "THIS IS A DRY RUN - use --execute"
        geonetwork = opts['geonetwork']
        maps = opts['maps']
        try:
            print 'checking layers not present in geoserver'
            pre_delete.disconnect(delete_layer, sender=Layer)
            cat = Layer.objects.gs_catalog
            storenames = [s.name for s in cat.get_stores()]
            layernames = [l.name for l in cat.get_resources()]
            for l in Layer.objects.all():
                if l.store not in storenames or l.name not in layernames:
                    self.delete_layer(l)
        except URLError:
            print "Couldn't connect to GeoServer; is it running? Make sure the GEOSERVER_BASE_URL setting is set correctly."
        finally:
            pre_delete.connect(delete_layer, sender=Layer)
        if args:
            print 'deleting specified layers'
            map(self.delete_by_uuid,args)
        if geonetwork:
            from xml.etree.ElementTree import XML
            print 'checking layers only found in geonetwork'
            uuids = set(Layer.objects.gn_catalog.get_all_layer_uuids())
            layers = [ v[0] for v in Layer.objects.values_list('uuid') ]
            uuids = uuids - set(layers)
            for u in uuids:
                if not self.dryrun:
                    # trick the template
                    layer = {'uuid' : u}
                    Layer.objects.gn_catalog.delete_layer(layer)
                md = Layer.objects.gn_catalog.get_by_uuid(u)
                dom = XML(md.xml)
                print '\t', dom.findall('.//{http://www.isotc211.org/2005/gmd}title')[0][0].text
        if maps:
            print 'checking for maps with missing layers'
            for m in list(Map.objects.all()):
                missing = []
                for l in m.layers:
                    localurl = l.ows_url and (l.ows_url == (settings.GEOSERVER_BASE_URL + "wms") or \
                        l.ows_url[0] == '/')
                    if localurl and Layer.objects.filter(typename=l.name).count() == 0:
                        missing.append(l.name)
                if missing:
                    if not self.dryrun:
                        m.delete()
                    print '\t', m, '(missing):', ' '.join(missing)

    def delete_by_uuid(self,uuid):
        import traceback
        layer = Layer.objects.filter(uuid=uuid)
        if len(layer) == 0:
            print 'could not locate layer %s' % uuid
        else:
            self.delete_layer(layer[0])

    def delete_layer(self,layer):
        if not self.dryrun:
            try:
                layer.delete()
            except Exception,ex:
                traceback.print_exc(ex)
        print '\t',layer

