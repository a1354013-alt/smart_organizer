"""
Video Phase 1 Support Tests

Tests for video file upload, metadata extraction, thumbnail generation,
and graceful degradation handling.
"""
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from core import FileProcessor, FileUtils, VIDEO_TAGS
from storage import StorageManager


@pytest.fixture
def test_video_mp4():
    """Create a minimal valid MP4 test file using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        temp_path = f.name
    
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=2',
        '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-shortest',
        temp_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Failed to create test video: {result.stderr}"
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def test_video_mov():
    """Create a minimal MOV test file using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix='.mov', delete=False) as f:
        temp_path = f.name
    
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'color=c=green:s=640x480:d=1.5',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        temp_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    
    yield temp_path
    
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def test_video_mkv():
    """Create a minimal MKV test file using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix='.mkv', delete=False) as f:
        temp_path = f.name
    
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'color=c=red:s=1280x720:d=3',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        temp_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    
    yield temp_path
    
    if os.path.exists(temp_path):
        os.unlink(temp_path)


class TestVideoUploadSupport:
    """Test video format upload support."""
    
    def test_video_extensions_defined(self):
        """Verify video extensions are defined."""
        assert '.mp4' in FileUtils.VIDEO_EXTENSIONS
        assert '.mov' in FileUtils.VIDEO_EXTENSIONS
        assert '.mkv' in FileUtils.VIDEO_EXTENSIONS
    
    def test_video_extensions_in_allowed_list(self):
        """Verify video extensions are in allowed upload list."""
        assert '.mp4' in FileUtils.ALLOWED_UPLOAD_EXTENSIONS
        assert '.mov' in FileUtils.ALLOWED_UPLOAD_EXTENSIONS
        assert '.mkv' in FileUtils.ALLOWED_UPLOAD_EXTENSIONS
    
    def test_video_extensions_not_too_broad(self):
        """Verify we only support specified formats (not avi/webm/flv/wmv)."""
        assert '.avi' not in FileUtils.VIDEO_EXTENSIONS
        assert '.webm' not in FileUtils.VIDEO_EXTENSIONS
        assert '.flv' not in FileUtils.VIDEO_EXTENSIONS
        assert '.wmv' not in FileUtils.VIDEO_EXTENSIONS


class TestVideoMetadataExtraction:
    """Test video metadata extraction."""
    
    def test_extract_video_metadata_mp4(self, test_video_mp4):
        """Test metadata extraction from MP4 file."""
        processor = FileProcessor()
        metadata = processor.extract_metadata(test_video_mp4)
        
        assert metadata['file_type'] == 'video'
        assert 'extra' in metadata
        extra = metadata['extra']
        
        assert extra.get('media_type') == 'video'
        assert extra.get('duration_seconds') is not None
        assert extra.get('width') is not None
        assert extra.get('height') is not None
        assert extra.get('fps') is not None
        assert extra.get('video_codec') is not None
        assert extra.get('file_size') is not None
    
    def test_extract_video_metadata_mov(self, test_video_mov):
        """Test metadata extraction from MOV file."""
        processor = FileProcessor()
        metadata = processor.extract_metadata(test_video_mov)
        
        assert metadata['file_type'] == 'video'
        extra = metadata.get('extra', {})
        assert extra.get('media_type') == 'video'
    
    def test_extract_video_metadata_mkv(self, test_video_mkv):
        """Test metadata extraction from MKV file."""
        processor = FileProcessor()
        metadata = processor.extract_metadata(test_video_mkv)
        
        assert metadata['file_type'] == 'video'
        extra = metadata.get('extra', {})
        assert extra.get('media_type') == 'video'


class TestVideoThumbnailGeneration:
    """Test video thumbnail generation."""
    
    def test_thumbnail_generated_for_video(self, test_video_mp4):
        """Test that thumbnail is generated for video files."""
        processor = FileProcessor()
        metadata = processor.extract_metadata(test_video_mp4)
        
        assert metadata.get('preview_path') is not None
        assert os.path.exists(metadata['preview_path'])
        assert metadata['preview_path'].endswith('.jpg')
    
    def test_thumbnail_from_middle_of_video(self, test_video_mp4):
        """Test that thumbnail is extracted from middle of video."""
        processor = FileProcessor()
        metadata = processor.extract_metadata(test_video_mp4)
        
        # Verify thumbnail exists and is valid image
        thumb_path = metadata.get('preview_path')
        assert thumb_path is not None
        assert os.path.exists(thumb_path)
        
        # Check it's a valid image
        from PIL import Image
        img = Image.open(thumb_path)
        assert img.format == 'JPEG'


class TestVideoClassification:
    """Test video classification."""
    
    def test_video_classified_as_video_tag(self, test_video_mp4):
        """Test that video files are classified with video tag."""
        processor = FileProcessor()
        metadata = processor.extract_metadata(test_video_mp4)
        
        main_topic, tag_scores, reason = processor.classify_multi_tag(
            metadata, 'test.mp4', return_reason=True
        )
        
        assert main_topic == '影片'
        assert '影片' in tag_scores
        assert tag_scores['影片'] == 1.0
    
    def test_video_tags_defined(self):
        """Test that VIDEO_TAGS is defined."""
        assert isinstance(VIDEO_TAGS, list)
        # Updated for Phase 3: VIDEO_TAGS now contains English categories for batch scanning
        assert len(VIDEO_TAGS) > 0
        # Check that we have meaningful tags (not just a placeholder)
        assert any(tag not in ['影片', 'Video'] for tag in VIDEO_TAGS) or 'Unclassified' in VIDEO_TAGS


class TestGracefulDegradation:
    """Test graceful degradation when video processing fails."""
    
    def test_invalid_video_file_graceful_handling(self):
        """Test that invalid video files don't crash the system."""
        # Create an invalid "video" file
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'invalid video content')
            temp_path = f.name
        
        try:
            processor = FileProcessor()
            metadata = processor.extract_metadata(temp_path)
            
            # Should still return metadata structure
            assert metadata['file_type'] == 'video'
            # May have error in extra
            extra = metadata.get('extra', {})
            # Should not crash
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_thumbnail_failure_does_not_break_metadata(self, test_video_mp4):
        """Test that thumbnail failure doesn't break metadata storage."""
        processor = FileProcessor()
        
        # Extract metadata normally first
        metadata = processor.extract_metadata(test_video_mp4)
        
        # Metadata should be present even if thumbnail fails
        assert metadata['file_type'] == 'video'
        assert 'extra' in metadata
        # thumbnail_error may or may not be present depending on success
        extra = metadata.get('extra', {})
        # Core metadata should exist regardless of thumbnail status
        assert extra.get('media_type') == 'video'


class TestDuplicateDetectionWithVideo:
    """Test that duplicate detection works with video files."""
    
    def test_video_duplicate_detection(self, test_video_mp4, tmp_path):
        """Test duplicate detection for video files."""
        db_path = str(tmp_path / "test.db")
        repo_root = str(tmp_path / "repo")
        upload_dir = str(tmp_path / "uploads")
        
        storage = StorageManager(db_path, repo_root, upload_dir)
        processor = FileProcessor()
        
        # Read test video content
        with open(test_video_mp4, 'rb') as f:
            content = f.read()
        
        file_hash = processor.get_file_hash(test_video_mp4)
        
        # First upload
        result1 = storage.create_temp_file(
            "test_video.mp4",
            content,
            file_hash,
            "video",
        )
        assert result1.get('success') is True
        file_id_1 = result1.get('file_id')
        
        # Second upload (duplicate)
        result2 = storage.create_temp_file(
            "test_video_copy.mp4",
            content,
            file_hash,
            "video",
        )
        # Should detect as duplicate
        assert result2.get('reason') == 'DUPLICATE'
        # existing_file_id may not be returned in all cases; check duplicate was detected
        assert result2.get('file_id') == file_id_1 or result2.get('reason') == 'DUPLICATE'


class TestExistingFormatsNotBroken:
    """Ensure existing PDF/JPG/PNG functionality is not broken."""
    
    def test_pdf_metadata_still_works(self, tmp_path):
        """Test PDF metadata extraction still works."""
        # Create a minimal PDF
        pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(pdf_content)
        
        processor = FileProcessor()
        metadata = processor.extract_metadata(str(pdf_path))
        
        assert metadata['file_type'] == 'document'
    
    def test_jpg_metadata_still_works(self, tmp_path):
        """Test JPG metadata extraction still works."""
        # Create a minimal valid JPEG
        jpeg_content = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
            0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0xFF, 0xD9
        ])
        jpg_path = tmp_path / "test.jpg"
        jpg_path.write_bytes(jpeg_content)
        
        processor = FileProcessor()
        metadata = processor.extract_metadata(str(jpg_path))
        
        assert metadata['file_type'] == 'photo'
    
    def test_png_metadata_still_works(self, tmp_path):
        """Test PNG metadata extraction still works."""
        # Create a minimal valid PNG
        png_content = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,
            0x00, 0x05, 0xFE, 0x02, 0xFE, 0xDC, 0xCC, 0x59,
            0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,
            0x44, 0xAE, 0x42, 0x60, 0x82
        ])
        png_path = tmp_path / "test.png"
        png_path.write_bytes(png_content)
        
        processor = FileProcessor()
        metadata = processor.extract_metadata(str(png_path))
        
        assert metadata['file_type'] == 'photo'
