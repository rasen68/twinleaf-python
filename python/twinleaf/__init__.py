from twinleaf import _twinleaf

class Device(_twinleaf._Device):
    def __new__(cls, url=None, route=None, announce=False, instantiate=True):
        device = super().__new__(cls, url, route)
        return device

    def __init__(self, url=None, route=None, announce=False, instantiate=True):
        super().__init__()
        if instantiate:
            self._instantiate_rpcs()
            self._instantiate_samples(announce)

    def _rpc_int(self, name: str, size: int, signed: bool, value: int | None = None) -> int:
        import struct
        match size, signed:
            case 1, True: fstr = '<b'
            case 2, True: fstr = '<h'
            case 4, True: fstr = '<i'
            case 1, False: fstr = '<B'
            case 2, False: fstr = '<H'
            case 4, False: fstr = '<I'
        payload = b'' if value is None else struct.pack(fstr, value)
        rep = self._rpc(name, payload)
        val = struct.unpack(fstr, rep)[0]
        del struct
        return val

    def _rpc_float(self, name: str, size: int, value: float | None = None) -> float:
        import struct
        fstr = '<f' if (size == 4) else '<d'
        payload = b'' if value is None else struct.pack(fstr, value)
        rep = self._rpc(name, payload)
        val = struct.unpack(fstr, rep)[0]
        del struct
        return val

    def _instantiate_rpcs(self):
        self._registry = self._rpc_registry()
        self.settings = RpcSurvey('settings')
        self._instantiate_rpcs_recursive(self.settings)

    def _instantiate_rpcs_recursive(self, parent, prefix=''):
        for child_name in self._registry.children_of(prefix):
            full_path = f'{prefix}.{child_name}' if prefix else child_name
            rpc = self._registry.find(full_path)
            attr_name = '_rpc' if child_name == 'rpc' else child_name

            if rpc is not None:
                child = Rpc(rpc, self)
            else:
                child = RpcSurvey(attr_name)
            setattr(parent, attr_name, child)
            self._instantiate_rpcs_recursive(child, full_path)

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

type _rpc_type = int | float | str | bytes | None
class _RpcNode:
    def __init__(self, name, device: Device):
        self.__name__ = name
        self._device = device

    def survey(self) -> dict[str, _rpc_type]:
        results = {}
        for name, attr in self.__dict__.items():
            if isinstance(attr, _RpcNode):
                # Check if it's an RPC that should be read
                if isinstance(attr, _RpcBase):
                    if attr._readable and attr._data_type is not None:
                        results[attr.__name__] = attr()

                # Recursively survey children (works for both Rpc and Survey)
                results |= attr.survey()
        return results

class _RpcBase(_RpcNode):
    def __init__(self, pyrpc: _twinleaf._Rpc, device: Device):
        super().__init__(pyrpc.name, device)
        self._size_bytes = pyrpc.size_bytes
        self._readable   = pyrpc.readable
        self._writable   = pyrpc.writable
        match pyrpc.type_str:
            case _ if _.startswith('i'): self._data_type, self._signed = int, True
            case _ if _.startswith('u'): self._data_type, self._signed = int, False
            case _ if _.startswith('f'): self._data_type = float
            case _ if _.startswith('s'): self._data_type = str
            case '' if self._size_bytes == 0: self._data_type = None
            case other: self._data_type = bytes

    def _call_with_arg(self, arg=None) -> _rpc_type:
        match self._data_type:
            case _ if _ is int:
                return self._device._rpc_int(self.__name__, self._size_bytes, self._signed, arg)
            case _ if _ is float:
                return self._device._rpc_float(self.__name__, self._size_bytes, arg)
            case _ if _ is str:
                return self._device._rpc(self.__name__, arg.encode()).decode()
            case _ if _ is bytes:
                return self._device._rpc(self.__name__, arg)
            case None:
                return self._device._rpc(self.__name__, b'')
            case other:
                raise TypeError(f"Invalid RPC type {other}, RPC types must be {_rpc_type}")

    def _call(self) -> _rpc_type:
        match self._data_type:
            case _ if _ is int:
                return self._device._rpc_int(self.__name__, self._size_bytes, self._signed)
            case _ if _ is float:
                return self._device._rpc_float(self.__name__, self._size_bytes)
            case _ if _ is str:
                return self._device._rpc(self.__name__, b'').decode()
            case _ if _ is bytes | None:
                return self._device._rpc(self.__name__, b'')
            case other:
                raise TypeError(f"Invalid RPC type {other}, RPC types must be {_rpc_type}")

class _RpcSurveyBase(_RpcNode):
    def __init__(self, name: str, device: Device):
        super().__init__(name, device)

    def __call__(self):
        return self.survey()

def _Rpc(pyrpc: _twinleaf._Rpc, device: Device) -> _RpcNode:
    if pyrpc.writable:
        def __call__(self, arg=None) -> _rpc_type:
            if arg is None:
                return self._call()
            else:
                return self._call_with_arg(arg)
    else:
        def __call__(self) -> _rpc_type:
            return self._call()

    cls = type('Rpc', (_RpcBase,), {'__call__': __call__})
    return cls(pyrpc, device)

def _RpcSurvey(name: str) -> _RpcNode:
    cls = type('Survey', (_RpcSurveyBase,), {})
    return cls(name, device)
