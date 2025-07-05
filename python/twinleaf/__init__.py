import twinleaf._twinleaf
import struct
from .itl import *

class Device(_twinleaf.Device):
    def __new__(cls, url=None, route=None, announce=False, instantiate=True):
        device = super().__new__(cls, url, route)
        return device

    def __init__(self, url=None, route=None, announce=False, instantiate=True):
        super().__init__()
        if instantiate:
            self._instantiate_rpcs()
            self._instantiate_samples(announce)

    def _rpc_int(self, name: str, size: int, signed: bool, value: int | None = None) -> int:
        # print(name)
        if signed:
            match size:
                case 1:
                    fstr = '<b'
                case 2:
                    fstr = '<h'
                case 4:
                    fstr = '<i'
        else:
            match size:
                case 1:
                    fstr = '<B'
                case 2:
                    fstr = '<H'
                case 4:
                    fstr = '<I'
        payload = b'' if value is None else struct.pack(fstr, value)
        rep = self._rpc(name, payload)
        return struct.unpack(fstr, rep)[0]

    def _rpc_float(self, name: str, size: int, value: float | None = None) -> float:
        fstr = '<f' if (size == 4) else '<d'
        payload = b'' if value is None else struct.pack(fstr, value)
        rep = self._rpc(name, payload)
        return struct.unpack(fstr, rep)[0]

    def _get_rpc_obj(self, name: str, meta: int):
        data_type = (meta & 0xF)
        data_size = (meta >> 4) & 0xF
        if (meta & 0x8000) == 0:
            def rpc_method(local_self, arg: bytes = b'') -> bytes:
                return self._rpc(name, arg)
        elif data_size == 0:
            def rpc_method(local_self) -> None:
                return self._rpc(name, b'')
        elif data_type in (0, 1):
            signed = (data_type) == 1
            if (meta & 0x0200) == 0:
                def rpc_method(local_self) -> int:
                    return self._rpc_int(name, data_size, signed)
            else:
                def rpc_method(local_self, arg: int | None = None) -> int:
                    return self._rpc_int(name, data_size, signed, arg)
        elif data_type == 2:
            if (meta & 0x0200) == 0:
                def rpc_method(local_self) -> float:
                    return self._rpc_float(name, data_size)
            else:
                def rpc_method(local_self, arg: float | None = None) -> float:
                    return self._rpc_float(name, data_size, arg)
        elif data_type == 3:
            if (meta & 0x0200) == 0:
                def rpc_method(local_self) -> str:
                    return self._rpc(name, b'').decode()
            else:
                def rpc_method(local_self, arg: str | None = None) -> str:
                    return self._rpc(name, arg.encode()).decode()
        cls = type('rpc',(), {'__name__':name, '__call__':rpc_method, '_data_type':data_type, '_data_size':data_size})
        return cls

    def _get_obj_survey(self, name: str):
        def survey(local_self):
            survey = {}
            for name, attr in local_self.__dict__.items():
                if callable(attr):
                    if hasattr(attr, '_data_type'):
                        # don't call actions like reset, stop, etc.
                        if attr._data_type > 0 or attr._data_size > 0:
                            survey[attr.__name__] = attr()
                    else:
                        if attr.__class__.__name__ == 'survey':
                            subsurvey = attr()
                            survey = {**survey, **subsurvey}
            return survey
        cls = type('survey',(), {'__name__':name, '__call__':survey})
        return cls

    def _instantiate_rpcs(self):
        n = int.from_bytes(self._rpc("rpc.listinfo", b""), "little")
        cls = self._get_obj_survey(self)
        setattr(self, 'settings', cls())
        for i in range(n):
            res = self._rpc("rpc.listinfo", i.to_bytes(2, "little"))
            meta = int.from_bytes(res[0:2], "little")
            name = res[2:].decode()

            mname, *prefix = reversed(name.split("."))
            parent = self.settings
            survey_prefix = ""
            if prefix and (prefix[-1] == "rpc"):
                prefix[-1] = "_rpc"
            for token in reversed(prefix):
                survey_prefix += "." + token
                if not hasattr(parent, token):
                    cls = self._get_obj_survey(token)
                    setattr(parent, token, cls())
                parent = getattr(parent, token)

            cls = self._get_rpc_obj(name, meta)
            setattr(parent, mname, cls())

    def _samples_dict(self, n: int = 1, stream: str = "", columns: list[str] = []):
        samples = list(self._samples(n, stream=stream, columns=columns))
        # bin into streams
        streams = {}
        for line in samples:
            stream_id = line.pop("stream", None)
            if stream_id not in streams:
                streams[stream_id] = { "stream": stream_id }
            for key, value in line.items():
                if key not in streams[stream_id]:
                    streams[stream_id][key] = []
                streams[stream_id][key].append(value)
        return streams

    def _samples_list(self, n: int = 1, stream: str = "", columns: list[str] = [], timeColumn = True, titleRow = True):
        streams = self._samples_dict(n, stream, columns)
        # Convert to list with rows of data. Not super happy about how inefficient this is. 
        if len(streams.items()) > 1:
            raise NotImplementedError("Stream concatenation not yet implemented for two different streams")
        stream = list(streams.values())[0]
        stream.pop('stream')
        if not timeColumn:
            stream.pop('time')
        dataColumns = [column for column in stream.values() ]
        dataRows = [list(row) for row in zip(*dataColumns)]
        if titleRow:
            columnNames = list(stream.keys());
            dataRows.insert(0,columnNames)
        return dataRows

    def _get_obj_samples_dict(self, name: str, stream: str = "", columns: list[str] = [], *args, **kwargs):
        def samples_method(local_self, *args, **kwargs):
            # print(f"Sampling {name} from stream {stream} with columns {columns}")
            return self._samples_dict(stream=stream, columns=columns, *args, **kwargs)
        cls = type('samplesDict'+name,(), {'__name__':name, '__call__':samples_method})
        return cls

    def _get_obj_samples_list(self, name: str, stream: str = "", columns: list[str] = [], *args, **kwargs):
        def samples_method(local_self, *args, **kwargs):
            # print(f"Sampling {name} from stream {stream} with columns {columns}")
            return self._samples_list(stream=stream, columns=columns, *args, **kwargs)
        cls = type('samplesList'+name,(), {'__name__':name, '__call__':samples_method})
        return cls

    def _instantiate_samples(self, announce: bool = False):
        metadata = self._get_metadata()
        dev_meta = metadata['device']
        if announce:
            print(f"{dev_meta['name']} ({dev_meta['serial_number']}) [{dev_meta['firmware_hash']}]")
        streams_flattened = []
        for stream, value in metadata['streams'].items():
            for column_name in value['columns'].keys():
                streams_flattened.append(stream+"."+column_name)

        # All samples        
        cls = self._get_obj_samples_dict("samples", stream="", columns=[])
        setattr(self, 'samples', cls())

        for stream_column in streams_flattened:
            mname, *prefix, stream = reversed(stream_column.split("."))
            parent = self.samples

            if not hasattr(parent, stream):
                # All samples for this stream
                cls = self._get_obj_samples_list(stream, stream=stream, columns=[])
                setattr(parent, stream, cls())
            parent = getattr(parent, stream)

            stream_prefix = ""
            for token in reversed(prefix):
                
                stream_prefix += "." + token
                if not hasattr(parent, token):
                    #wildcard columns
                    cls = self._get_obj_samples_list(token, stream=stream, columns=[stream_prefix[1:]+".*"])
                    setattr(parent, token, cls())
                parent = getattr(parent, token)

            # specific stream samples
            stream, column_name = stream_column.split(".",1)

            cls = self._get_obj_samples_list(mname, stream=stream, columns=[column_name])
            setattr(parent, mname, cls())

    def _interact(self):
        imported_objects = {}
        imported_objects["tl"] = self
        try:
            import IPython
            IPython.embed(
                user_ns=imported_objects, 
                banner1="", 
                banner2="", # Use   : {self._shortname}.<tab>
                exit_msg="",
                enable_tip=False)
        except ImportError:
            import code
            repl = code.InteractiveConsole(locals=imported_objects)
            repl.interact(
                banner = "", 
                exitmsg = "")

__doc__ = twinleaf.__doc__
if hasattr(twinleaf, "__all__"):
    __all__ = twinleaf.__all__
