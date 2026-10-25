"""GGUF preset selection and Windows CPU runtime are configured without private data."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from ghost_box.models import download, settings as profiles
from ghost_box.ui.caspy import ModelPanel
from ghost_box.ui.window import prepare_qt_plugins


class GGUFPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins();cls.app=QApplication.instance() or QApplication([])

    def test_preset_resolves_verified_gguf_file_and_restores_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=QSettings(str(Path(directory)/'settings.ini'),QSettings.Format.IniFormat)
            payload=b'GGUF synthetic model'
            manifest=download.GGUF_MANIFEST | {'files':[dict(name='Qwen_Qwen3.5-4B-Q4_K_M.gguf',
                       size=len(payload),algorithm='sha256',digest=hashlib.sha256(payload).hexdigest())]}
            with (patch('ghost_box.ui.caspy.QSettings',return_value=settings),
                  patch('ghost_box.ui.caspy.QStandardPaths.writableLocation',return_value=directory),
                  patch.dict(download.PRESETS,{download.GGUF_PRESET:manifest})):
                panel=ModelPanel()
                panel.selector.setCurrentIndex(panel.selector.findData(download.GGUF_PRESET))
                self.assertIsNone(panel.selected_folder())
                self.assertTrue(panel.download_button.isEnabled())
                panel.gguf_folder.mkdir(parents=True)
                file=panel.gguf_folder/manifest['files'][0]['name'];file.write_bytes(payload)
                (panel.gguf_folder/'download-complete.json').write_text(json.dumps(manifest))
                panel.update_status()
                self.assertEqual(panel.selected_folder(),file)
                self.assertFalse(panel.download_button.isEnabled())
                self.assertEqual(panel.parameters()['max_output_tokens'],2048)
                panel.controls['temperature'].setValue(0.25);panel.save_parameters()
                restored=ModelPanel()
                self.assertEqual(restored.selector.currentData(),download.GGUF_PRESET)
                self.assertEqual(restored.selected_folder(),file)
                self.assertEqual(restored.parameters()['temperature'],0.25)
                panel.deleteLater();restored.deleteLater()

    def test_windows_default_dependency_uses_locked_upstream_cpu_wheel(self):
        root=Path(__file__).resolve().parents[1]
        project=tomllib.loads((root/'pyproject.toml').read_text())
        self.assertIn("llama-cpp-python==0.3.36 ; sys_platform == 'win32'",project['project']['dependencies'])
        lock=tomllib.loads((root/'uv.lock').read_text())
        cpu=next(package for package in lock['package'] if package['name']=='llama-cpp-python'
                 and 'github.com/abetlen/' in package['source'].get('url',''))
        self.assertTrue(any(wheel['url'].endswith('win_amd64.whl') and wheel.get('hash','').startswith('sha256:')
                            for wheel in cpu['wheels']))

    def test_removal_waits_for_loaded_worker_to_exit(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QMessageBox
        from ghost_box.ui.window import Window
        payload=b'GGUF synthetic model'
        manifest=download.GGUF_MANIFEST | {'files':[dict(name='Qwen_Qwen3.5-4B-Q4_K_M.gguf',size=len(payload),
                  algorithm='sha256',digest=hashlib.sha256(payload).hexdigest())]}
        with tempfile.TemporaryDirectory() as directory:
            settings=QSettings(str(Path(directory)/'settings.ini'),QSettings.Format.IniFormat)
            with (patch('ghost_box.ui.caspy.QSettings',return_value=settings),patch('ghost_box.ui.window.QSettings',return_value=settings),
                  patch('ghost_box.ui.window.QStandardPaths.writableLocation',return_value=directory),
                  patch('ghost_box.mail.gmail.saved_account',return_value=''),
                  patch.dict(download.PRESETS,{download.GGUF_PRESET:manifest})):
                owner=Window();owner.task.wait()
                for _ in range(10):self.app.processEvents()
                folder=owner.caspy.gguf_folder;folder.mkdir(parents=True)
                file=folder/manifest['files'][0]['name'];file.write_bytes(payload)
                (folder/'download-complete.json').write_text(json.dumps(manifest))
                owner.caspy.selector.setCurrentIndex(owner.caspy.selector.findData(download.GGUF_PRESET))
                owner.runtime.worker_arguments=['-u',str(Path(__file__).parent/'fixtures/model_worker.py')]
                def wait_for(predicate):
                    loop=QEventLoop();poll=QTimer();poll.setInterval(2)
                    poll.timeout.connect(lambda:loop.quit() if predicate() else None)
                    end=QTimer();end.setSingleShot(True);end.timeout.connect(loop.quit)
                    poll.start();end.start(3000)
                    if not predicate():loop.exec()
                    poll.stop();end.stop()
                    self.assertTrue(predicate())
                owner.runtime.load(file,{'tokens':10})
                wait_for(lambda:owner.runtime.state=='ready')
                remove=download.remove_preset
                def checked_remove(root,key):
                    self.assertIsNone(owner.runtime.process)
                    return remove(root,key)
                with (patch('ghost_box.ui.window.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel),
                      patch('ghost_box.models.download.remove_preset') as call):
                    owner.remove_preset();call.assert_not_called()
                self.assertTrue(file.exists())
                with (patch('ghost_box.ui.window.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes),
                      patch('ghost_box.models.download.remove_preset',side_effect=checked_remove) as call):
                    owner.remove_preset()
                    self.assertTrue(file.exists())
                    wait_for(lambda:owner.caspy.task is None and not folder.exists())
                    call.assert_called_once()
                self.assertIsNone(owner.caspy.selected_folder())
                self.assertTrue(owner.caspy.download_button.isEnabled())
                self.assertTrue(owner.caspy.parameter_file.exists())
                owner.close()
